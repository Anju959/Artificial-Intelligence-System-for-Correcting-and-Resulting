import os
import re
import logging
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, UnidentifiedImageError
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pymysql
import json

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App & DB setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret-default-key")

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'mysql+pymysql://root:root@localhost/ai_grading_system')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class StudentScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hall_ticket_number = db.Column(db.String(50), nullable=False)
    scores = db.Column(db.Text, nullable=False) # JSON literal
    total_score = db.Column(db.Float, nullable=False)

def create_database():
    """Ensure the ai_grading_system database exists."""
    try:
        connection = pymysql.connect(host='localhost', user='root', password='root')
        with connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE IF NOT EXISTS ai_grading_system;")
        connection.commit()
        connection.close()
    except Exception as e:
        logger.error(f"Error creating database: {e}. Ensure MySQL is running with root:root credentials.")

with app.app_context():
    create_database()
    db.drop_all()  # Ensure old schema is wiped
    db.create_all()

UPLOAD_FOLDER = Path('static/uploads')
QUESTION_FOLDER = UPLOAD_FOLDER / 'questions'
ANSWER_FOLDER   = UPLOAD_FOLDER / 'answers'
CONFIG_FILE     = QUESTION_FOLDER / 'config.txt'

QUESTION_FOLDER.mkdir(parents=True, exist_ok=True)
ANSWER_FOLDER.mkdir(parents=True, exist_ok=True)

# Tesseract path
TESSERACT_CMD = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import fitz

def extract_text_from_file(filepath: Path) -> str:
    """Extract text from a PDF or image file."""
    text = ""
    try:
        if filepath.suffix.lower() == '.pdf':
            logger.info(f"Extracting PDF text: {filepath}")
            doc = fitz.open(filepath)
            for page in doc:
                text += page.get_text()
        else:
            logger.info(f"OCR image: {filepath}")
            img = Image.open(str(filepath))
            text += pytesseract.image_to_string(img)
    except UnidentifiedImageError:
        logger.error(f"Cannot identify image file: {filepath}")
    except Exception as e:
        logger.error(f"OCR error for {filepath}: {e}")
    return text.strip()


def split_text_by_questions(full_text: str, num_questions: int) -> list[str]:
    """
    Split extracted text into `num_questions` chunks.

    Strategy:
    1. Try to detect numbered markers: Q1 / 1. / Question 1 / (1) etc.
    2. If markers found, use them to split.
    3. Fall back to equal-length splitting if markers cannot be found.
    """
    if num_questions <= 1:
        return [full_text]

    # Build a regex that matches common question prefixes
    pattern = re.compile(
        r'(?:^|\n)\s*(?:Q(?:uestion)?\s*\.?\s*(\d+)|(\d+)\s*[.):]\s)',
        re.IGNORECASE
    )
    matches = list(pattern.finditer(full_text))

    if len(matches) >= num_questions:
        # Detected markers — split at each match
        parts = []
        for i, m in enumerate(matches[:num_questions]):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
            parts.append(full_text[start:end].strip())
        return parts

    # Fallback: split roughly into equal chunks by characters
    logger.warning("Could not find question markers; splitting evenly.")
    chunk_size = max(1, len(full_text) // num_questions)
    return [
        full_text[i * chunk_size: (i + 1) * chunk_size].strip()
        for i in range(num_questions)
    ]


def calculate_similarity(text1: str, text2: str) -> float:
    """Return cosine-similarity percentage (0–100) between two strings."""
    if not text1 or not text2:
        return 0.0
    try:
        vectorizer = TfidfVectorizer()
        tfidf = vectorizer.fit_transform([text1, text2])
        sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
        return round(float(sim) * 100, 2)
    except Exception as e:
        logger.error(f"Similarity error: {e}")
        return 0.0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/faculty/upload', methods=['GET', 'POST'])
def faculty_upload():
    """
    Faculty uploads:
      - Number of questions
      - Model answers PDF (required)
    The backend OCRs the PDF, splits into per-question chunks,
    and saves each as model_answer_<n>.txt.
    """
    if request.method == 'POST':
        num_questions_str = request.form.get('num_questions', '').strip()
        if not num_questions_str or not num_questions_str.isdigit() or int(num_questions_str) < 1:
            return "Please provide a valid number of questions.", 400
        num_questions = int(num_questions_str)

        ans_file   = request.files.get('answer_file')
        q_file     = request.files.get('question_file')

        if not ans_file or not ans_file.filename:
            return "Model Answers PDF is required.", 400

        # Save and OCR the model answers file
        ans_filename = secure_filename('model_answers_' + ans_file.filename)
        ans_filepath = QUESTION_FOLDER / ans_filename
        try:
            ans_file.save(str(ans_filepath))
            model_text = extract_text_from_file(ans_filepath)
        except Exception as e:
            logger.error(f"Failed to process model answers file: {e}")
            return "Error processing model answers file.", 500

        if not model_text:
            return "Could not extract any text from the model answers PDF. Check the file quality.", 400

        # Split into per-question chunks
        chunks = split_text_by_questions(model_text, num_questions)
        # Pad or trim to exact count
        while len(chunks) < num_questions:
            chunks.append("")
        chunks = chunks[:num_questions]

        # Persist each chunk
        try:
            for i, chunk in enumerate(chunks, start=1):
                (QUESTION_FOLDER / f"model_answer_{i}.txt").write_text(chunk, encoding='utf-8')
            CONFIG_FILE.write_text(str(num_questions), encoding='utf-8')
        except IOError as e:
            logger.error(f"Failed to write model answer files: {e}")
            return "Failed to save data on server.", 500

        # Save question file if provided (for reference)
        if q_file and q_file.filename:
            q_filename = secure_filename('questions_' + q_file.filename)
            try:
                q_file.save(str(QUESTION_FOLDER / q_filename))
            except Exception as e:
                logger.warning(f"Could not save question file: {e}")

        logger.info(f"Faculty uploaded {num_questions} question(s). Model answers split and saved.")
        return redirect(url_for('index'))

    return render_template('faculty_upload.html')


@app.route('/student/upload', methods=['GET', 'POST'])
def student_upload():
    """
    Student uploads:
      - Roll number / Student ID
      - Answer sheet PDF (single file)
    The backend OCRs it, splits into the same number of questions,
    and scores each against the corresponding model answer.
    """
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        file = request.files.get('answer_file')

        if not student_id:
            return "Student ID is required.", 400
        if not file or not file.filename:
            return "Answer file is required.", 400

        # Load config
        if not CONFIG_FILE.exists():
            abort(404, description="No exam has been set up yet. Ask the faculty to upload first.")
        try:
            num_questions = int(CONFIG_FILE.read_text(encoding='utf-8').strip())
        except Exception:
            abort(500, description="Error reading exam configuration.")

        # Save + OCR student answer
        filename = secure_filename(f"{student_id}_{file.filename}")
        filepath = ANSWER_FOLDER / filename
        try:
            file.save(str(filepath))
            student_text = extract_text_from_file(filepath)
        except Exception as e:
            logger.error(f"Failed to process student file: {e}")
            return "Error processing uploaded file.", 500

        # Split student text into per-question chunks
        student_chunks = split_text_by_questions(student_text, num_questions)
        while len(student_chunks) < num_questions:
            student_chunks.append("")
        student_chunks = student_chunks[:num_questions]

        # Grade each question
        results = []
        for i in range(1, num_questions + 1):
            model_path = QUESTION_FOLDER / f"model_answer_{i}.txt"
            if not model_path.exists():
                logger.warning(f"Model answer for Q{i} missing.")
                model_answer_text = ""
            else:
                model_answer_text = model_path.read_text(encoding='utf-8')

            student_answer_text = student_chunks[i - 1]
            similarity = calculate_similarity(model_answer_text, student_answer_text)
            score = round(similarity / 10, 1)   # 0–100% → 0–10

            logger.info(f"Student {student_id} Q{i}: Similarity={similarity}%, Score={score}/10")
            results.append({
                'question_number': i,
                'similarity': similarity,
                'score': score,
            })
            
        total_score  = round(sum(r['score'] for r in results), 1)
        max_score    = num_questions * 10
        percentage   = round((total_score / max_score) * 100, 1) if max_score > 0 else 0.0

        # Save single row to database!
        try:
            scores_dict = {f"Q{r['question_number']}": r['score'] for r in results}
            db_score = StudentScore(
                hall_ticket_number=student_id,
                scores=json.dumps(scores_dict),
                total_score=total_score
            )
            db.session.add(db_score)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to save student scores to database: {e}")

        return render_template(
            'result.html',
            student_id=student_id,
            results=results,
            total_score=total_score,
            max_score=max_score,
            percentage=percentage,
        )

    student_id = request.args.get('student_id', '')
    return render_template('student_upload.html', student_id=student_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    port       = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "True").lower() in ("true", "1", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
