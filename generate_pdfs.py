from fpdf import FPDF
import os

def create_pdf(text, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in text.split('\n'):
        pdf.cell(200, 10, txt=line, ln=True, align='L')
    pdf.output(filename)

# Mock Model Answers
model_answers_text = """Question 1
The mitochondria is the powerhouse of the cell.
It is responsible for generating most of the cell's supply of adenosine triphosphate (ATP).

Question 2
Photosynthesis is a process used by plants and other organisms to convert light energy into chemical energy.
"""

# Mock Student Answers
student_answers_text = """Question 1.
The mitochondria is known to be the powerhouse of a cell, responsible for ATP generation.

Question 2.
Photosynthesis is the process that plants use to make food from sunlight.
"""

os.makedirs("test_data", exist_ok=True)
create_pdf(model_answers_text, "test_data/model_answers.pdf")
create_pdf(student_answers_text, "test_data/student_answers.pdf")

print("Created PDFs successfully in test_data folder.")
