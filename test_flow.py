import requests
import re
from bs4 import BeautifulSoup

base_url = 'http://localhost:5000'

def run_test():
    print("1. Faculty Upload")
    with open('test_data/model_answers.pdf', 'rb') as f:
        resp = requests.post(
            f"{base_url}/faculty/upload",
            data={'num_questions': '2'},
            files={'answer_file': ('model_answers.pdf', f, 'application/pdf')}
        )
    print("Faculty Upload Status:", resp.status_code)
    if resp.status_code != 200:
        print("Faculty Upload Response:", resp.text)
    
    print("\n2. Student Upload")
    with open('test_data/student_answers.pdf', 'rb') as f:
        resp = requests.post(
            f"{base_url}/student/upload",
            data={'student_id': '22C31A6701'},
            files={'answer_file': ('student_answers.pdf', f, 'application/pdf')}
        )
    print("Student Upload Status:", resp.status_code)
    
    if resp.status_code == 200:
        print("\n--- Output Score Page ---")
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Extract the hall ticket
        student_id_h2 = soup.find('h2', class_='hero-title')
        if student_id_h2:
            print(student_id_h2.text.strip())
            
    if resp.status_code == 200:
        print("\n--- Output Score Page Saved ---")
        with open('output_snapshot.html', 'w', encoding='utf-8') as f:
            f.write(resp.text)

if __name__ == '__main__':
    run_test()
