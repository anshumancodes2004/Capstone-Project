from flask import Flask, render_template, request, redirect, session, jsonify, current_app
import mysql.connector
import mysql.connector.pooling
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from datetime import datetime, timedelta
import smtplib
import random
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import threading
import re
import os
import logging
from werkzeug.exceptions import TooManyRequests
import cv2
import numpy as np
import base64
from ultralytics import YOLO
import requests
from dotenv import load_dotenv
import io
import re
import time
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from sentence_transformers import SentenceTransformer


# ============================================================
# .env se saari secrets load karo
# ============================================================
load_dotenv()

app = Flask(__name__)


# ============================================================
# Strong random secret key — .env se
# ============================================================
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable set nahi hai! "
        ".env file check karo. "
        "Generate karne ke liye run karo: "
        "python -c \"import secrets; print(secrets.token_hex(32))\""
    )


# ============================================================
# DB credentials .env se + Connection Pooling
# ============================================================
db_pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="oems_pool",
    pool_size=10,
    host=os.environ.get("DB_HOST", "localhost"),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASS"),      # .env se aayega
    database=os.environ.get("DB_NAME", "exam_system")
)


# ---------------- DATABASE CONNECTION ----------------
def get_db_connection():
    return db_pool.get_connection()


# ============================================================
# Sentence-BERT Model Load
# ============================================================
print("[OEMS] Loading evaluation model...")
try:
    sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
    print("[OEMS] Model ready!")
except Exception as e:
    sbert_model = None
    print(f"[OEMS] Model load failed: {e}")


# ---------------- BROWSER + CAMPUS HELPERS ----------------
CAMPUS_IP_RANGES = [
    "10.104.242",
]

def is_secure_browser():
    return request.headers.get('X-OEMS-Secure-Browser') == 'ElectronV1'

def is_campus_ip():
    client_ip = request.remote_addr
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        client_ip = forwarded.split(',')[0].strip()
    return any(client_ip.startswith(p) for p in CAMPUS_IP_RANGES)


# ============================================================
# PDF GENERATOR
# ============================================================
def generate_result_pdf(student, exam, answers, total_score, percentage):
    """
    Student exam result ka PDF generate karo.
    Returns: bytes (PDF file content)
    """
    buffer = io.BytesIO()
 
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
 
    styles = getSampleStyleSheet()
 
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=22,
        textColor=colors.HexColor('#1e293b'),
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=13,
        textColor=colors.HexColor('#4f46e5'),
        spaceBefore=14,
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#374151'),
        spaceAfter=4,
        leading=16
    )
    muted_style = ParagraphStyle(
        'Muted',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#6b7280'),
        spaceAfter=3
    )
    center_style = ParagraphStyle(
        'Center',
        parent=styles['Normal'],
        alignment=TA_CENTER,
        fontSize=10,
        textColor=colors.HexColor('#374151')
    )
 
    story = []
 
    # ── HEADER ──
    story.append(Paragraph("OEMS — Examination Result Report", title_style))
    story.append(HRFlowable(
        width="100%", thickness=2,
        color=colors.HexColor('#4f46e5'), spaceAfter=12
    ))
 
    # ── SECTION 1: Student Details ──
    story.append(Paragraph("Section 1: Student Details", heading_style))
 
    student_name  = str(student.get('name', 'N/A'))
    student_email = str(student.get('email', 'N/A') or 'Not provided')
    exam_title    = str(exam.get('title', 'N/A'))
    exam_date     = str(exam.get('start_time', 'N/A'))
    admission_no  = str(student.get('admission_no', 'N/A'))
    program       = str(student.get('program', 'N/A'))
    semester      = str(student.get('semester', 'N/A'))
 
    detail_data = [
        ['Field', 'Value'],
        ['Student Name',    student_name],
        ['Admission No',    admission_no],
        ['Email',           student_email],
        ['Program',         f"{program} — Semester {semester}"],
        ['Exam Name',       exam_title],
        ['Exam Date',       exam_date],
        ['Report Generated', datetime.now().strftime('%d %b %Y, %I:%M %p')],
    ]
 
    detail_table = Table(detail_data, colWidths=[5*cm, 12*cm])
    detail_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,0), colors.HexColor('#4f46e5')),
        ('TEXTCOLOR',   (0,0), (-1,0), colors.white),
        ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,0), 10),
        ('BACKGROUND',  (0,1), (0,-1), colors.HexColor('#f1f5f9')),
        ('FONTNAME',    (0,1), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,1), (-1,-1), 10),
        ('TEXTCOLOR',   (0,1), (-1,-1), colors.HexColor('#374151')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1),
            [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID',        (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING',     (0,0), (-1,-1), 8),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(detail_table)
    story.append(Spacer(1, 16))
 
    # ── SECTION 2: Question-wise Analysis ──
    story.append(Paragraph("Section 2: Question-wise Analysis", heading_style))
 
    for idx, ans in enumerate(answers, 1):
        q_text       = str(ans.get('question_text', 'N/A'))
        student_ans  = str(ans.get('student_answer', '') or '').strip()
        q_marks      = ans.get('marks', 0)
        score        = ans.get('score', 0) or 0
        feedback     = str(ans.get('feedback', 'Pending evaluation') or 'Pending evaluation')
 
        if not student_ans:
            student_ans = 'Not Answered'
 
        # Question block
        q_bg = colors.HexColor('#fefce8') if score == 0 else colors.HexColor('#f0fdf4')
 
        q_data = [
            [Paragraph(f'<b>Q{idx}.</b> {q_text}', normal_style), ''],
            ['Student Answer:', Paragraph(student_ans, normal_style)],
            ['Marks Obtained:', Paragraph(
                f'<b>{score} / {q_marks}</b>',
                ParagraphStyle('Score', parent=normal_style,
                    textColor=colors.HexColor('#16a34a') if score > 0
                    else colors.HexColor('#dc2626'))
            )],
            ['AI Feedback:', Paragraph(feedback, muted_style)],
        ]
 
        q_table = Table(q_data, colWidths=[4*cm, 13*cm])
        q_table.setStyle(TableStyle([
            ('SPAN',        (0,0), (-1,0)),
            ('BACKGROUND',  (0,0), (-1,0), colors.HexColor('#eef2ff')),
            ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND',  (0,1), (0,-1), colors.HexColor('#f8fafc')),
            ('FONTNAME',    (0,1), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE',    (0,0), (-1,-1), 10),
            ('GRID',        (0,0), (-1,-1), 0.3, colors.HexColor('#e2e8f0')),
            ('PADDING',     (0,0), (-1,-1), 8),
            ('VALIGN',      (0,0), (-1,-1), 'TOP'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1),
                [colors.white, colors.HexColor('#fafafa')]),
        ]))
        story.append(q_table)
        story.append(Spacer(1, 8))
 
    story.append(PageBreak())
 
    # ── SECTION 3: Summary ──
    story.append(Paragraph("Section 3: Performance Summary", heading_style))
 
    total_q     = len(answers)
    attempted   = sum(1 for a in answers
                      if str(a.get('student_answer', '') or '').strip())
    not_attempted = total_q - attempted
    max_marks   = sum(a.get('marks', 0) for a in answers)
    pct         = round(percentage, 1)
 
    # Grade
    if pct >= 90:   grade, grade_color = 'O (Outstanding)', '#16a34a'
    elif pct >= 75: grade, grade_color = 'A (Excellent)',   '#22c55e'
    elif pct >= 60: grade, grade_color = 'B (Good)',        '#3b82f6'
    elif pct >= 45: grade, grade_color = 'C (Average)',     '#f59e0b'
    elif pct >= 35: grade, grade_color = 'D (Pass)',        '#f97316'
    else:           grade, grade_color = 'F (Fail)',        '#ef4444'
 
    summary_data = [
        ['Metric', 'Value'],
        ['Total Questions',     str(total_q)],
        ['Attempted',           str(attempted)],
        ['Not Attempted',       str(not_attempted)],
        ['Total Score',         f'{total_score} / {max_marks}'],
        ['Percentage',          f'{pct}%'],
        ['Grade',               grade],
    ]
 
    summary_table = Table(summary_data, colWidths=[8*cm, 9*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,0), colors.HexColor('#4f46e5')),
        ('TEXTCOLOR',   (0,0), (-1,0), colors.white),
        ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,0), 10),
        ('BACKGROUND',  (0,1), (0,-1), colors.HexColor('#f1f5f9')),
        ('FONTNAME',    (0,1), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,1), (-1,-1), 11),
        ('ROWBACKGROUNDS', (0,1), (-1,-1),
            [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID',        (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING',     (0,0), (-1,-1), 10),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 16))
 
    # ── SECTION 4: AI Overall Feedback ──
    story.append(Paragraph("Section 4: AI Performance Feedback", heading_style))
 
    if pct >= 75:
        overall_fb = (f"Excellent performance! The student demonstrated strong understanding "
                      f"of the subject matter, scoring {pct}%. Keep up the great work.")
    elif pct >= 50:
        overall_fb = (f"Good attempt. The student scored {pct}% showing adequate understanding. "
                      f"Review the questions where marks were deducted to improve further.")
    elif pct >= 35:
        overall_fb = (f"The student scored {pct}%. While the basic concepts are understood, "
                      f"more practice and deeper study of the subject is recommended.")
    else:
        overall_fb = (f"The student scored {pct}%. Significant improvement is needed. "
                      f"Please review the course material thoroughly and seek guidance.")
 
    fb_table = Table(
        [[Paragraph(overall_fb, normal_style)]],
        colWidths=[17*cm]
    )
    fb_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#eef2ff')),
        ('BORDER',     (0,0), (-1,-1), 1, colors.HexColor('#c7d2fe')),
        ('PADDING',    (0,0), (-1,-1), 12),
    ]))
    story.append(fb_table)
    story.append(Spacer(1, 20))
 
    # ── SECTION 5: Footer ──
    story.append(HRFlowable(
        width="100%", thickness=1,
        color=colors.HexColor('#e2e8f0'), spaceBefore=10
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Generated by OEMS — Online Examination Management System | "
        f"{datetime.now().strftime('%d %b %Y, %I:%M %p')}",
        ParagraphStyle('Footer', parent=muted_style,
                       alignment=TA_CENTER, fontSize=8)
    ))
 
    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ---------------- AI EVALUATION HELPER ----------------
def evaluate_answer(question, student_answer, max_marks, model_answer=None):
    """
    Hybrid: Sentence-BERT + TF-IDF + Keyword scoring
    3 layers — offline, no internet, no API needed.
 
    model_answer: agar admin ne provide kiya hai toh
                  student answer usse compare hoga (better accuracy)
                  nahi hai toh question se compare hoga
    """
    if not student_answer or len(student_answer.strip()) < 10:
        return 0, "Answer too short or not provided."
 
    word_count = len(student_answer.split())
    if word_count < 5:
        return 0, "Answer too short to evaluate."
 
    student_clean = student_answer.strip().lower()
 
    # Reference text — model answer hai toh woh use karo,
    # nahi hai toh question se compare karo
    if model_answer and len(model_answer.strip()) > 10:
        reference_text  = model_answer.strip()
        reference_clean = reference_text.lower()
        comparison_mode = "model_answer"
    else:
        reference_text  = question.strip()
        reference_clean = question.strip().lower()
        comparison_mode = "question"
 
    print(f"[Eval] Mode: {comparison_mode}")
 
    # ── Layer 1: Keyword Overlap ──
    stop_words = {
        'what','is','are','the','a','an','of','in','to',
        'and','or','for','with','how','why','explain',
        'describe','define','write','give','list','state'
    }
    ref_words = set(reference_clean.split()) - stop_words
    s_words   = set(student_clean.split())
 
    keyword_score = 0.0
    if ref_words:
        matched      = ref_words & s_words
        keyword_score = len(matched) / len(ref_words)
 
    # ── Layer 2: TF-IDF Cosine Similarity ──
    tfidf_score = 0.0
    try:
        vectorizer   = TfidfVectorizer(stop_words='english', min_df=1)
        tfidf_matrix = vectorizer.fit_transform([reference_clean, student_clean])
        tfidf_score  = float(
            cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        )
    except Exception:
        tfidf_score = keyword_score
 
    # ── Layer 3: Sentence-BERT Semantic Similarity ──
    sbert_score = 0.0
    if sbert_model is not None:
        try:
            embeddings  = sbert_model.encode([reference_text, student_answer])
            sbert_score = float(
                cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
            )
            sbert_score = max(0.0, sbert_score)
        except Exception as e:
            print(f"[SBERT] Error: {e}")
            sbert_score = (keyword_score + tfidf_score) / 2
    else:
        sbert_score = (keyword_score + tfidf_score) / 2
 
    # ── Weighted Average ──
    combined = (
        sbert_score   * 0.60 +
        tfidf_score   * 0.25 +
        keyword_score * 0.15
    )
    combined = max(0.0, min(1.0, combined))
 
    # Length bonus
    if word_count >= 80:
        combined = min(1.0, combined + 0.05)
    elif word_count >= 40:
        combined = min(1.0, combined + 0.02)
 
    # Score calculate karo
    raw_score = combined * float(max_marks)
    score     = round(raw_score * 2) / 2  # 0.5 steps
 
    # Feedback
    if combined >= 0.75:
        feedback = f"Excellent answer. Concepts clearly explained. Score: {score}/{max_marks}."
    elif combined >= 0.55:
        feedback = f"Good attempt. Key concepts covered. Score: {score}/{max_marks}."
    elif combined >= 0.35:
        feedback = f"Partial answer. More detail needed. Score: {score}/{max_marks}."
    elif combined >= 0.15:
        feedback = f"Minimal relevance to the question. Score: {score}/{max_marks}."
    else:
        feedback = f"Answer does not address the question. Score: {score}/{max_marks}."
 
    print(f"[Eval] SBERT={sbert_score:.2f} TFIDF={tfidf_score:.2f} "
          f"KW={keyword_score:.2f} → {score}/{max_marks}")
 
    return score, feedback


# ============================================================
# BACKGROUND EVALUATION FUNCTION
# ============================================================
def run_background_evaluation(student_id, exam_id, app_context):
    with app_context:
        try:
            conn   = get_db_connection()
            cursor = conn.cursor(dictionary=True)
 
            # correct_answer bhi fetch karo
            cursor.execute("""
                SELECT a.id, a.answer, q.question_text,
                       q.marks, q.question_type, q.correct_answer
                FROM answers a
                JOIN questions q ON a.question_id = q.id
                WHERE a.student_id = %s
                  AND a.exam_id   = %s
                  AND q.question_type = 'theory'
                  AND a.score IS NULL
            """, (student_id, exam_id))
            theory_answers = cursor.fetchall()
 
            print(f"[BG Eval] Student {student_id}, Exam {exam_id} "
                  f"— {len(theory_answers)} answers")
 
            for i, ans in enumerate(theory_answers):
                student_answer = (ans['answer'] or '').strip()
 
                if not student_answer or len(student_answer) < 10:
                    score, feedback = 0, "No answer submitted or too short."
                else:
                    score, feedback = evaluate_answer(
                        ans['question_text'],
                        student_answer,
                        ans['marks'],
                        model_answer=ans.get('correct_answer', '')
                    )
 
                cursor.execute(
                    "UPDATE answers SET score=%s, feedback=%s WHERE id=%s",
                    (round(score, 1), feedback, ans['id'])
                )
                print(f"[BG Eval] #{ans['id']} → {score}/{ans['marks']}")
 
            conn.commit()
 
            # Total score recalculate
            cursor.execute("""
                SELECT COALESCE(SUM(a.score), 0) AS total
                FROM answers a
                WHERE a.student_id = %s AND a.exam_id = %s
            """, (student_id, exam_id))
            total_score = float(cursor.fetchone()['total'] or 0)
 
            # Results update
            cursor.execute("""
                UPDATE results
                SET total_score = %s, submission_status = 'Evaluated'
                WHERE student_id = %s AND exam_id = %s
            """, (round(total_score, 2), student_id, exam_id))
            conn.commit()
 
            print(f"[BG Eval] Results updated — Total: {total_score}")
 
            # Student + Exam + Answers for PDF
            cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
            student = cursor.fetchone()
 
            cursor.execute("SELECT * FROM exams WHERE id = %s", (exam_id,))
            exam = cursor.fetchone()
 
            cursor.execute("""
                SELECT q.question_text, q.marks, q.question_type,
                       a.answer AS student_answer, a.score, a.feedback
                FROM answers a
                JOIN questions q ON a.question_id = q.id
                WHERE a.student_id = %s AND a.exam_id = %s
                ORDER BY q.id
            """, (student_id, exam_id))
            all_answers = cursor.fetchall()
 
            cursor.close()
            conn.close()
 
            for ans in all_answers:
                if ans['score']          is None: ans['score']          = 0
                if not ans['feedback']:           ans['feedback']        = 'Evaluated'
                if not ans['student_answer']:     ans['student_answer']  = ''
 
            max_marks  = sum(a['marks'] for a in all_answers)
            percentage = (total_score / max_marks * 100) if max_marks > 0 else 0
 
            pdf_bytes = generate_result_pdf(
                student, exam, all_answers, total_score, percentage
            )
 
            student_email = student.get('email')
            if student_email and is_valid_email(student_email):
                send_result_email(student, exam, total_score, percentage, pdf_bytes)
            else:
                print(f"[BG Eval] No email — skipped")
 
        except Exception as e:
            print(f"[BG Eval] ERROR: {e}")
            import traceback
            traceback.print_exc()


# ============================================================
# RESULT EMAIL SENDER
# ============================================================
def send_result_email(student, exam, total_score, percentage, pdf_bytes):
    """Student ko result email bhejo with PDF attachment."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    from email.utils import formataddr
 
    try:
        student_name  = student.get('name', 'Student')
        student_email = student.get('email')
        exam_title    = exam.get('title', 'Exam')
 
        msg = MIMEMultipart('mixed')
        msg['From']    = formataddr(('OEMS Examination', EMAIL_CONFIG['SENDER_EMAIL']))
        msg['To']      = student_email
        msg['Subject'] = f"Your Result: {exam_title} — OEMS"
 
        pct = round(percentage, 1)
        if pct >= 35:
            result_word  = "PASS"
            result_color = "#16a34a"
        else:
            result_word  = "FAIL"
            result_color = "#dc2626"
 
        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#f4f7f6;padding:20px;">
        <table align="center" width="100%"
               style="max-width:550px;background:#fff;border-radius:10px;
                      border:1px solid #e2e8f0;overflow:hidden;margin:0 auto;">
            <tr>
                <td style="background:#4f46e5;padding:20px;text-align:center;">
                    <h2 style="margin:0;color:#fff;font-size:20px;">
                        Exam Result — OEMS
                    </h2>
                </td>
            </tr>
            <tr>
                <td style="padding:24px;">
                    <p style="color:#374151;">Hi <b>{student_name}</b>,</p>
                    <p style="color:#374151;">
                        Your result for <b>{exam_title}</b> has been evaluated.
                    </p>
 
                    <table width="100%"
                           style="background:#f8fafc;border-radius:8px;
                                  border:1px solid #e2e8f0;padding:16px;
                                  margin:16px 0;">
                        <tr>
                            <td style="color:#374151;font-weight:bold;">
                                Total Score:
                            </td>
                            <td style="color:#374151;text-align:right;">
                                <b>{total_score}</b>
                            </td>
                        </tr>
                        <tr>
                            <td style="color:#374151;font-weight:bold;">
                                Percentage:
                            </td>
                            <td style="color:#374151;text-align:right;">
                                <b>{pct}%</b>
                            </td>
                        </tr>
                        <tr>
                            <td style="color:#374151;font-weight:bold;">
                                Result:
                            </td>
                            <td style="text-align:right;">
                                <b style="color:{result_color};">{result_word}</b>
                            </td>
                        </tr>
                    </table>
 
                    <p style="color:#6b7280;font-size:13px;">
                        Detailed question-wise analysis is attached as a PDF report.
                    </p>
                    <p style="color:#374151;margin-top:20px;">
                        <b>OEMS Examination Team</b>
                    </p>
                </td>
            </tr>
        </table>
        </body></html>
        """
 
        msg.attach(MIMEText(html, 'html'))
 
        # PDF attach karo
        pdf_part = MIMEBase('application', 'octet-stream')
        pdf_part.set_payload(pdf_bytes)
        encoders.encode_base64(pdf_part)
        safe_name = exam_title.replace(' ', '_')[:30]
        pdf_part.add_header(
            'Content-Disposition',
            f'attachment; filename="OEMS_Result_{safe_name}.pdf"'
        )
        msg.attach(pdf_part)
 
        with smtplib.SMTP(
            EMAIL_CONFIG['SMTP_SERVER'],
            EMAIL_CONFIG['SMTP_PORT']
        ) as server:
            server.starttls()
            server.login(
                EMAIL_CONFIG['SENDER_EMAIL'],
                EMAIL_CONFIG['APP_PASSWORD']
            )
            server.sendmail(
                EMAIL_CONFIG['SENDER_EMAIL'],
                student_email,
                msg.as_string()
            )
 
        print(f"[Email] Result sent to {student_email}")
 
    except Exception as e:
        print(f"[Email] Failed: {e}")


# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("home.html")


# ---------------- STUDENT LOGIN ROUTE ----------------
@app.route("/student_login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        admission_no = request.form.get("admission_no")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM students WHERE admission_no=%s",
            (admission_no,)
        )
        student = cursor.fetchone()
        cursor.close()
        conn.close()

        if student and check_password_hash(student["password"], password):
            session["student_id"] = student["id"]
            session["role"] = "student"
            session["student_name"] = student["name"]
            session["admission_no"] = student["admission_no"]
            session["program"] = student["program"]
            session["branch"] = student["branch"]
            session["semester"] = student["semester"]
            return redirect("/student")
        else:
            return "Invalid Admission Number or Password ❌"

    return render_template("student_login.html")


# ---------------- ADMIN LOGIN ROUTE ----------------
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        admin_id = request.form.get("admin_id")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM admins WHERE admin_id=%s",
            (admin_id,)
        )
        admin = cursor.fetchone()
        cursor.close()
        conn.close()

        if admin and check_password_hash(admin["password"], password):
            session["admin_id"] = admin["admin_id"]
            session["role"] = "admin"
            session["admin_name"] = admin["name"]
            session["admin_branch"] = admin["branch"]
            return redirect("/admin")
        else:
            return "Invalid Admin ID or Password ❌"

    return render_template("admin_login.html")


# ---------------- ROLE BASED PROTECTION ----------------
def login_required(role):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if role == "admin":
                if "admin_id" not in session:
                    return redirect("/")
            elif role == "student":
                if "student_id" not in session:
                    return redirect("/")
            return f(*args, **kwargs)
        return decorated_function
    return wrapper


# ---------------- ADMIN DASHBOARD ROUTE ----------------
@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    admin_branch = session.get("admin_branch")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if admin_branch == "ALL":
        cursor.execute("SELECT * FROM exams")
        exams = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) AS total FROM students")
        total_students = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) AS total FROM exams WHERE status='publish'")
        active_exams = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) AS total FROM answers WHERE score IS NULL")
        pending_ai_checks = cursor.fetchone()["total"]
    else:
        cursor.execute("SELECT * FROM exams WHERE branch = %s", (admin_branch,))
        exams = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) AS total FROM students WHERE branch = %s", (admin_branch,))
        total_students = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) AS total FROM exams WHERE status='publish' AND branch = %s", (admin_branch,))
        active_exams = cursor.fetchone()["total"]
        cursor.execute("""
            SELECT COUNT(a.id) AS total
            FROM answers a
            JOIN exams e ON a.exam_id = e.id
            WHERE a.score IS NULL AND e.branch = %s
        """, (admin_branch,))
        pending_ai_checks = cursor.fetchone()["total"]

    cursor.close()
    conn.close()
    return render_template(
        "admin_dashboard.html",
        exams=exams,
        total_students=total_students,
        active_exams=active_exams,
        pending_ai_checks=pending_ai_checks,
        admin_branch=admin_branch
    )


# ---------------- ADMIN STUDENT MANAGEMENT ROUTE ----------------
@app.route("/student_manager")
@login_required("admin")
def students():
    admin_branch = session.get("admin_branch")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if admin_branch == "ALL":
        cursor.execute("SELECT * FROM students ORDER BY program, semester, name, admission_no")
    else:
        cursor.execute("""
            SELECT * FROM students WHERE branch = %s
            ORDER BY program, semester, name, admission_no
        """, (admin_branch,))

    students = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("student_manager.html", students=students, admin_branch=admin_branch)


# ---------------- ADD STUDENT ROUTE ----------------
@app.route("/add_student", methods=["GET", "POST"])
@login_required("admin")
def add_student():
    admin_branch = session.get("admin_branch")

    if request.method == "POST":
        name = request.form["name"]
        admission_no = request.form["admission_no"]
        program = request.form["program"]
        semester = request.form["semester"]
        branch = request.form.get("branch") if admin_branch == "ALL" else admin_branch

        default_password = "OEMS@12345"
        hashed_password = generate_password_hash(default_password)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO students (name, admission_no, program, branch, semester, password)
        VALUES (%s,%s,%s,%s,%s,%s)
        """, (name, admission_no, program, branch, semester, hashed_password))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect("/student_manager")

    return render_template("add_student.html", admin_branch=admin_branch)


# ---------------- EDIT PROFILE STUDENT ROUTE ----------------
@app.route("/edit_profile", methods=["GET", "POST"])
@login_required("student")
def edit_profile():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    student_id = session["student_id"]

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if password:
            hashed_password = generate_password_hash(password)
            cursor.execute("""
            UPDATE students SET email=%s, password=%s WHERE id=%s
            """, (email, hashed_password, student_id))
        else:
            cursor.execute("""
            UPDATE students SET email=%s WHERE id=%s
            """, (email, student_id))

        conn.commit()

        # FIX: Session email DB se re-fetch karo, form input se directly set mat karo
        cursor.execute("SELECT email FROM students WHERE id=%s", (student_id,))
        fresh = cursor.fetchone()
        session["email"] = fresh["email"]

        cursor.close()
        conn.close()
        return redirect("/student")

    cursor.execute("SELECT * FROM students WHERE id=%s", (student_id,))
    user = cursor.fetchone()
    session["program"] = user["program"]
    session["semester"] = user["semester"]
    cursor.close()
    conn.close()
    return render_template("edit_profile.html", user=user)


# ---------------- RESET AI EVALUATION ROUTE ----------------
@app.route("/reset_ai_evaluation")
@login_required("admin")
def reset_ai_evaluation():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE answers
    JOIN questions ON answers.question_id = questions.id
    SET answers.score = NULL, answers.feedback = NULL
    WHERE questions.question_type = 'theory'
    """)
    conn.commit()
    cursor.close()
    conn.close()
    return "AI Evaluation Reset Successfully"


# ---------------- CREATE EXAM ROUTE ----------------
@app.route("/create_exam", methods=["GET", "POST"])
@login_required("admin")
def create_exam():
    admin_branch = session.get("admin_branch")
 
    if request.method == "POST":
        title         = request.form["title"]
        exam_type     = request.form["exam_type"]
        total_marks   = request.form["total_marks"]
        program       = request.form["program"]
        semester      = request.form["semester"]
        start_time    = request.form["start_time"]
        duration      = request.form["duration"]
        browser_mode  = request.form.get("browser_mode", "any")
        ai_proctoring = 1 if request.form.get("ai_proctoring") == "1" else 0
        branch        = request.form.get("branch") if admin_branch == "ALL" else admin_branch
 
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO exams
        (title, exam_type, total_marks, program, branch, semester,
         start_time, duration, status, browser_mode, ai_proctoring)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
        """, (title, exam_type, total_marks, program, branch, semester,
              start_time, duration, browser_mode, ai_proctoring))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect("/admin")
 
    return render_template("create_exam.html", admin_branch=admin_branch)


# ---------------- ADD QUESTION ROUTE ----------------
@app.route("/add_question/<int:exam_id>", methods=["GET", "POST"])
@login_required("admin")
def add_question(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM exams WHERE id=%s", (exam_id,))
    exam = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as total FROM questions WHERE exam_id=%s", (exam_id,))
    question_count = cursor.fetchone()["total"]
    max_limit = 20 if exam["exam_type"] == "theory" else 50

    if request.method == "POST":
        if question_count >= max_limit:
            cursor.close()
            conn.close()
            return "Maximum question limit reached ❌"

        question_text = request.form["question_text"]
        marks = request.form["marks"]
        question_type = request.form.get("question_type")
        optionA = request.form.get("optionA")
        optionB = request.form.get("optionB")
        optionC = request.form.get("optionC")
        optionD = request.form.get("optionD")
        correct_answers_list = request.form.getlist("correct_answer")

        if correct_answers_list:
            correct_answers_list.sort()
            correct_answer = ", ".join(correct_answers_list)
        else:
            correct_answer = request.form.get("correct_answer", "")

        cursor.execute("""
            INSERT INTO questions
            (exam_id, question_text, question_type, optionA, optionB, optionC, optionD, correct_answer, marks)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (exam_id, question_text, question_type, optionA, optionB, optionC, optionD, correct_answer, marks))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(f"/add_question/{exam_id}")

    cursor.close()
    conn.close()
    return render_template("add_question.html", exam=exam, question_count=question_count, max_limit=max_limit)


# ============================================================
# QUESTION EDIT ROUTE
# ============================================================
@app.route("/edit_question/<int:question_id>", methods=["GET", "POST"])
@login_required("admin")
def edit_question(question_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM questions WHERE id=%s", (question_id,))
    question = cursor.fetchone()

    if not question:
        cursor.close()
        conn.close()
        return "Question not found", 404

    if request.method == "POST":
        question_text = request.form.get("question_text")
        optionA = request.form.get("optionA")
        optionB = request.form.get("optionB")
        optionC = request.form.get("optionC")
        optionD = request.form.get("optionD")
        marks = request.form.get("marks")

        # AUTO DETECT TYPE
        is_mcq = optionA or optionB or optionC or optionD

        if is_mcq:
            selected_options = request.form.getlist("correct_answer")
            correct_answer = ",".join(selected_options) if selected_options else ""
        else:
            correct_answer = request.form.get("correct_answer", "")

        cursor.execute("""
            UPDATE questions
            SET question_text=%s,
                optionA=%s,
                optionB=%s,
                optionC=%s,
                optionD=%s,
                correct_answer=%s,
                marks=%s
            WHERE id=%s
        """, (
            question_text,
            optionA,
            optionB,
            optionC,
            optionD,
            correct_answer,
            marks,
            question_id
        ))

        conn.commit()
        exam_id = question["exam_id"]

        cursor.close()
        conn.close()

        return redirect(f"/questions/{exam_id}")

    cursor.close()
    conn.close()

    return render_template("edit_question.html", question=question)


# ---------------- DELETE QUESTION ROUTE ----------------
@app.route("/delete_question/<int:question_id>", methods=["POST"])
@login_required("admin")
def delete_question(question_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT exam_id FROM questions WHERE id=%s", (question_id,))
    question = cursor.fetchone()
    exam_id = question["exam_id"] if question else None
    cursor.execute("DELETE FROM questions WHERE id=%s", (question_id,))
    conn.commit()
    cursor.close()
    conn.close()
    if exam_id:
        return redirect(f"/questions/{exam_id}")
    return redirect("/admin")


# ---------------- DELETE EXAM ROUTE ----------------
@app.route("/delete_exam/<int:exam_id>", methods=["POST"])
@login_required("admin")
def delete_exam(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    DELETE answers FROM answers
    JOIN questions ON answers.question_id = questions.id
    WHERE questions.exam_id=%s
    """, (exam_id,))
    cursor.execute("DELETE FROM results WHERE exam_id=%s", (exam_id,))
    cursor.execute("DELETE FROM questions WHERE exam_id=%s", (exam_id,))
    cursor.execute("DELETE FROM exams WHERE id=%s", (exam_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect("/admin")


# ---------------- EXAM PUBLISH ROUTE ----------------
@app.route("/publish_exam/<int:exam_id>")
@login_required("admin")
def publish_exam(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE exams SET status='publish' WHERE id=%s", (exam_id,))
        cursor.execute("""
            SELECT title, start_time, duration, program, branch, semester
            FROM exams WHERE id=%s
        """, (exam_id,))
        exam_data = cursor.fetchone()

        if exam_data:
            exam_name, exam_date, duration, target_program, target_branch, target_semester = [str(x) for x in exam_data]
            cursor.execute("""
                SELECT name, email FROM students
                WHERE program=%s AND branch=%s AND semester=%s
            """, (target_program, target_branch, target_semester))
            students_data = cursor.fetchall()
            student_list = [{"name": row[0], "email": row[1]} for row in students_data]

            if student_list:
                def send_emails_async():
                    try:
                        result = email_service.send_bulk_exam_alerts(student_list, exam_name, exam_date, duration)
                        print(f"Bulk email result: {result}")
                    except Exception as e:
                        print(f"Error sending bulk emails: {e}")
                threading.Thread(target=send_emails_async).start()

        conn.commit()
    except Exception as e:
        print(f"Error publishing exam: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

    return redirect("/admin")


# ---------------- EXAM UNPUBLISH ROUTE ----------------
@app.route("/unpublish_exam/<int:exam_id>")
@login_required("admin")
def unpublish_exam(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE exams SET status='draft' WHERE id=%s", (exam_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect("/admin")


# ---------------- RESULTS SUMMARY ROUTE ----------------
@app.route("/results")
@login_required("admin")
def results_summary():
    admin_branch = session.get("admin_branch")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if admin_branch == "ALL":
        cursor.execute("""
            SELECT students.id AS student_id, students.name AS student_name,
                   students.admission_no, students.program, students.branch, students.semester,
                   exams.id AS exam_id, exams.title AS exam_title,
                   results.total_score, results.submission_status
            FROM results
            JOIN students ON results.student_id = students.id
            JOIN exams ON results.exam_id = exams.id
            ORDER BY results.id DESC
        """)
    else:
        cursor.execute("""
            SELECT students.id AS student_id, students.name AS student_name,
                   students.admission_no, students.program, students.branch, students.semester,
                   exams.id AS exam_id, exams.title AS exam_title,
                   results.total_score, results.submission_status
            FROM results
            JOIN students ON results.student_id = students.id
            JOIN exams ON results.exam_id = exams.id
            WHERE students.branch = %s
            ORDER BY results.id DESC
        """, (admin_branch,))

    results_data = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("results_summary.html", results=results_data, admin_branch=admin_branch)


# ---------------- RESULT DETAILS ROUTE ----------------
@app.route("/result_details/<int:student_id>/<int:exam_id>")
@login_required("admin")
def result_details(student_id, exam_id):
    admin_branch = session.get("admin_branch")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT branch FROM students WHERE id = %s", (student_id,))
    student = cursor.fetchone()

    if not student:
        cursor.close()
        conn.close()
        return "Student not found ❌", 404

    if admin_branch != "ALL" and student["branch"] != admin_branch:
        cursor.close()
        conn.close()
        return "Access Denied: Aap sirf apni branch ke students ka result dekh sakte hain! 🚫", 403

    cursor.execute("""
        SELECT answers.id, questions.question_text, questions.marks,
               answers.answer AS student_answer, answers.score, answers.feedback
        FROM answers
        JOIN questions ON answers.question_id = questions.id
        WHERE answers.student_id=%s AND answers.exam_id=%s
    """, (student_id, exam_id))
    answers = cursor.fetchall()

    for a in answers:
        if a['score'] is None:
            a['score'] = 0

    cursor.close()
    conn.close()
    return render_template("result_details.html", answers=answers)


# ---------------- VIEW QUESTIONS ----------------
@app.route("/questions/<int:exam_id>")
@login_required("admin")
def view_questions(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM questions WHERE exam_id=%s", (exam_id,))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("questions.html", questions=questions, exam_id=exam_id)


# ---------------- STUDENT DASHBOARD ----------------
@app.route("/student")
@login_required("student")
def student_dashboard():
    from datetime import datetime, timedelta

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. Fresh student info DB se
    cursor.execute("SELECT * FROM students WHERE id = %s", (session.get("student_id"),))
    student_info = cursor.fetchone()

    if not student_info:
        cursor.close()
        conn.close()
        return "Student data not found. Please login again.", 404

    # 2. Available exams fetch karo
    cursor.execute("""
        SELECT * FROM exams
        WHERE program=%s AND branch=%s AND semester=%s AND status='publish'
    """, (student_info["program"], student_info["branch"], student_info["semester"]))
    exams = cursor.fetchall()

    # 3. FIX: Ye exams fetch karo jo student ne already attempt kiye hain
    #    Taaki "Start Exam" button disable ho sake attempted exams pe
    cursor.execute("""
        SELECT exam_id FROM results
        WHERE student_id = %s
    """, (session.get("student_id"),))
    attempted_rows = cursor.fetchall()
    attempted_exam_ids = {row["exam_id"] for row in attempted_rows}

    cursor.close()
    conn.close()

    # 4. FIX: Server time pass karo — countdown timers ke liye
    now_time = datetime.now()

    return render_template(
        "student_dashboard.html",
        student=student_info,
        exams=exams,
        attempted_exam_ids=attempted_exam_ids,  # NEW
        now_time=now_time,                       # NEW
        timedelta=timedelta                      # Jinja2 mein timedelta use ke liye
    )


# ---------------- START EXAM ROUTE ----------------
@app.route("/start_exam/<int:exam_id>")
@login_required("student")
def start_exam(exam_id):
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
 
    cursor.execute("SELECT * FROM exams WHERE id=%s", (exam_id,))
    exam = cursor.fetchone()
 
    if not exam:
        cursor.close()
        conn.close()
        return "<script>alert('Exam not found!'); window.location.href='/student';</script>"
 
    exam_start = exam["start_time"]
    exam_end   = exam_start + timedelta(minutes=exam["duration"])
    now        = datetime.now()
 
    if now < exam_start:
        cursor.close()
        conn.close()
        start_str = exam_start.strftime("%I:%M %p")
        return f"<script>alert('Exam has not started yet. Starts at {start_str}'); window.location.href='/student';</script>"
 
    if now > exam_end:
        cursor.close()
        conn.close()
        return "<script>alert('Exam time is over.'); window.location.href='/student';</script>"
 
    # Re-entry check
    cursor.execute("""
        SELECT id FROM results
        WHERE student_id=%s AND exam_id=%s
    """, (session["student_id"], exam_id))
    existing_attempt = cursor.fetchone()
 
    if existing_attempt:
        cursor.close()
        conn.close()
        return """
        <script>
        alert("Security Alert: You have already attempted this exam. Re-entry is strictly prohibited.");
        window.location.href="/student";
        </script>
        """
 
    # ── Browser Mode + Campus IP Check ──
    browser_mode  = exam.get("browser_mode", "any")
    ai_proctoring = bool(exam.get("ai_proctoring", 0))
 
    if browser_mode in ("secure_any", "secure_campus"):
        if not is_secure_browser():
            cursor.close()
            conn.close()
            return render_template(
                "secure_browser_required.html",
                exam=exam,
                mode=browser_mode
            )
 
    if browser_mode == "secure_campus":
        if not is_campus_ip():
            cursor.close()
            conn.close()
            return render_template(
                "campus_only.html",
                exam=exam,
                client_ip=request.remote_addr
            )
 
    # Fetch questions
    cursor.execute("SELECT * FROM questions WHERE exam_id=%s", (exam_id,))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
 
    random.shuffle(questions)
 
    exam_start_str = exam_start.strftime("%Y-%m-%dT%H:%M:%S")
    exam_end_str   = exam_end.strftime("%Y-%m-%dT%H:%M:%S")
 
    return render_template(
        "start_exam.html",
        questions=questions,
        exam_id=exam_id,
        exam=exam,
        exam_start=exam_start_str,
        exam_end=exam_end_str,
        duration=exam["duration"],
        ai_proctoring=ai_proctoring,
    )


# ---------------- SUBMIT EXAM ROUTE ----------------
@app.route("/submit_exam/<int:exam_id>", methods=["POST"])
@login_required("student")
def submit_exam(exam_id):
    answers_data = request.form
    student_id   = session.get("student_id")
 
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
 
    # Duplicate submission check
    cursor.execute(
        "SELECT id FROM results WHERE student_id=%s AND exam_id=%s",
        (student_id, exam_id)
    )
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return render_template('already_submitted.html'), 400
 
    cursor.execute("SELECT * FROM questions WHERE exam_id=%s", (exam_id,))
    questions = cursor.fetchall()
 
    total_score = 0
    has_theory  = False
 
    for q in questions:
        q_type = q["question_type"].lower()
 
        if q_type == "mcq":
            student_answer = answers_data.get(f"q{q['id']}", "").strip()
            if student_answer == q["correct_answer"]:
                score    = q["marks"]
                feedback = "Correct answer"
            else:
                score    = 0
                feedback = "Incorrect or no answer"
            total_score += score
 
            cursor.execute("""
                INSERT INTO answers
                (student_id, exam_id, question_id, answer, score, feedback)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (student_id, exam_id, q["id"],
                  student_answer, score, feedback))
 
        elif q_type == "msq":
            student_answers_list = answers_data.getlist(f"q{q['id']}")
            student_answers_list.sort()
            student_answer = ", ".join(student_answers_list)
 
            db_correct = sorted([
                a.strip() for a in (q["correct_answer"] or "").split(",")
                if a.strip()
            ])
            db_correct_str = ", ".join(db_correct)
 
            if student_answer == db_correct_str and student_answer:
                score    = q["marks"]
                feedback = "Correct answers"
            else:
                score    = 0
                feedback = "Incorrect or partially correct"
            total_score += score
 
            cursor.execute("""
                INSERT INTO answers
                (student_id, exam_id, question_id, answer, score, feedback)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (student_id, exam_id, q["id"],
                  student_answer, score, feedback))
 
        else:
            # Theory — score NULL, background mein evaluate hoga
            has_theory     = True
            student_answer = answers_data.get(f"q{q['id']}", "").strip()
            cursor.execute("""
                INSERT INTO answers
                (student_id, exam_id, question_id, answer, score, feedback)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (student_id, exam_id, q["id"],
                  student_answer, None, "Pending AI evaluation"))
 
    # ── Initial result save ──
    # Theory hai toh Pending, warna Evaluated
    initial_status = "Pending" if has_theory else "Evaluated"
 
    cursor.execute("""
        INSERT INTO results
        (student_id, exam_id, total_score, submission_status)
        VALUES (%s, %s, %s, %s)
    """, (student_id, exam_id, round(total_score, 2), initial_status))
 
    conn.commit()
    cursor.close()
    conn.close()
 
    # ── Background evaluation trigger ──
    if has_theory:
        # Flask app context background thread mein pass karo
        app_ctx = app.app_context()
        thread  = threading.Thread(
            target=run_background_evaluation,
            args=(student_id, exam_id, app_ctx),
            daemon=True
        )
        thread.start()
        print(f"[Submit] Background evaluation started for "
              f"student {student_id}, exam {exam_id}")
 
    # ── Success page ──
    return render_template(
        'exam_submitted.html',
        has_theory=has_theory,
        objective_score=round(total_score, 2)
    )


# ---------------- DELETE STUDENT ROUTE ----------------
@app.route("/delete_student/<int:id>", methods=["POST"])
@login_required("admin")
def delete_student(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM answers WHERE student_id=%s", (id,))
    cursor.execute("DELETE FROM results WHERE student_id=%s", (id,))
    cursor.execute("DELETE FROM students WHERE id=%s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect("/student_manager")


# ---------------- AI CHECKING ROUTE ----------------
@app.route("/run_ai_check")
@login_required("admin")
def run_ai_check():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
 
    # correct_answer bhi fetch karo — model answer ke liye
    cursor.execute("""
        SELECT
            answers.id,
            answers.answer,
            answers.student_id,
            answers.exam_id,
            questions.question_text,
            questions.marks,
            questions.correct_answer
        FROM answers
        JOIN questions ON answers.question_id = questions.id
        WHERE answers.score IS NULL
          AND questions.question_type = 'theory'
    """)
    records = cursor.fetchall()
 
    print(f"[AI Check] Pending theory answers: {len(records)}")
 
    for r in records:
        student_answer = (r["answer"] or "").strip()
 
        if not student_answer or len(student_answer) < 10:
            cursor.execute(
                "UPDATE answers SET score=%s, feedback=%s WHERE id=%s",
                (0, "No answer submitted or too short.", r["id"])
            )
            continue
 
        score, feedback = evaluate_answer(
            r["question_text"],
            student_answer,
            r["marks"],
            model_answer=r.get("correct_answer", "")  # model answer pass karo
        )
 
        print(f"[AI Check] Answer #{r['id']} → {score}/{r['marks']}")
 
        cursor.execute(
            "UPDATE answers SET score=%s, feedback=%s WHERE id=%s",
            (round(score, 1), feedback, r["id"])
        )
 
    conn.commit()
 
    # FIX: results table bhi update karo — student wise
    # Unique student+exam combinations dhundho
    cursor.execute("""
        SELECT DISTINCT answers.student_id, answers.exam_id
        FROM answers
        JOIN questions ON answers.question_id = questions.id
        WHERE questions.question_type = 'theory'
    """)
    student_exams = cursor.fetchall()
 
    for se in student_exams:
        sid = se["student_id"]
        eid = se["exam_id"]
 
        # Total score recalculate karo
        cursor.execute("""
            SELECT COALESCE(SUM(score), 0) AS total
            FROM answers
            WHERE student_id = %s AND exam_id = %s
        """, (sid, eid))
        total = float(cursor.fetchone()["total"] or 0)
 
        # Koi bhi score NULL bacha hai?
        cursor.execute("""
            SELECT COUNT(*) AS pending
            FROM answers
            WHERE student_id = %s AND exam_id = %s
              AND score IS NULL
        """, (sid, eid))
        pending = cursor.fetchone()["pending"]
 
        new_status = "Pending" if pending > 0 else "Evaluated"
 
        cursor.execute("""
            UPDATE results
            SET total_score = %s, submission_status = %s
            WHERE student_id = %s AND exam_id = %s
        """, (round(total, 2), new_status, sid, eid))
 
    conn.commit()
    cursor.close()
    conn.close()
 
    print(f"[AI Check] Done — {len(records)} answers processed")
    return f"AI Evaluation Complete — {len(records)} answers evaluated."


# ---------------- PLAGIARISM DETECTION ROUTE ----------------
@app.route("/plagiarism/<int:exam_id>")
@login_required("admin")
def plagiarism_check(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
    SELECT students.name, answers.answer
    FROM answers
    JOIN students ON answers.student_id = students.id
    JOIN questions ON answers.question_id = questions.id
    WHERE questions.exam_id=%s AND questions.question_type = 'theory'
    """, (exam_id,))
    data = cursor.fetchall()
    cursor.close()
    conn.close()

    student_answers = {}
    for row in data:
        name = row["name"]
        ans = row["answer"]
        if not ans or not ans.strip():
            continue
        if name not in student_answers:
            student_answers[name] = ""
        student_answers[name] += " " + ans

    names = list(student_answers.keys())
    texts = list(student_answers.values())
    similarity_results = []
    cheaters = set()

    if len(texts) > 1:
        try:
            vectors = TfidfVectorizer().fit_transform(texts)
            sim_matrix = cosine_similarity(vectors)
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    sim = round(sim_matrix[i][j] * 100, 2)
                    similarity_results.append({"student1": names[i], "student2": names[j], "similarity": sim})
                    if sim > 80:
                        cheaters.add(names[i])
                        cheaters.add(names[j])
        except ValueError:
            pass

    return render_template("plagiarism.html", similarity_results=similarity_results, cheaters=cheaters)


# ============================================================
# FIX 5: /detect_cheating pe authentication add kiya
# ============================================================
import cv2
import numpy as np
import base64
from ultralytics import YOLO

try:
    phone_model = YOLO("yolov8n.pt")
    print("YOLO Loaded Successfully")
except Exception as e:
    print("YOLO Load Error:", e)
    phone_model = None

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')


@app.route("/detect_cheating", methods=["POST"])
@login_required("student")   # FIX: Unauthenticated access band
def detect_cheating():
    # Extra check: session se student validate karo
    if "student_id" not in session:
        return jsonify({"cheating": False}), 401

    try:
        data = request.json
        if not data or "image" not in data:
            return jsonify({"cheating": False})

        image_data = data["image"].split(",")[1]
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({"cheating": False})

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(100, 100))

        if len(faces) == 0:
            return jsonify({"cheating": True, "reason": "Face not visible / Looking away"})

        if len(faces) > 1:
            return jsonify({"cheating": True, "reason": f"Multiple faces detected ({len(faces)})"})

        x, y, w, h = faces[0]
        face_roi = gray[y:y + h, x:x + w]

        eyes = eye_cascade.detectMultiScale(face_roi, 1.1, 3)
        if len(eyes) == 0:
            return jsonify({"cheating": True, "reason": "Eyes not visible - Looking away"})

        face_center_x = x + w / 2
        face_center_y = y + h / 2
        img_center_x = img.shape[1] / 2
        img_center_y = img.shape[0] / 2
        x_offset = (face_center_x - img_center_x) / (img.shape[1] / 2)
        y_offset = (face_center_y - img_center_y) / (img.shape[0] / 2)

        if x_offset > 0.25:
            return jsonify({"cheating": True, "reason": "Looking Right"})
        if x_offset < -0.25:
            return jsonify({"cheating": True, "reason": "Looking Left"})
        if y_offset > 0.25:
            return jsonify({"cheating": True, "reason": "Looking Down (Suspicious)"})
        if y_offset < -0.25:
            return jsonify({"cheating": True, "reason": "Looking Up"})

        if phone_model is not None:
            results = phone_model(img, verbose=False, conf=0.30)
            for r in results:
                for box in r.boxes:
                    label = phone_model.names[int(box.cls)]
                    if label in ["cell phone", "mobile phone", "phone"]:
                        return jsonify({"cheating": True, "reason": "Mobile phone detected"})

        return jsonify({"cheating": False})

    except Exception as e:
        print("AI Error Log:", e)
        return jsonify({"cheating": False})


# ============================================================
# EMAIL SERVICE (FIX: Credentials .env se)
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMAIL_CONFIG = {
    'SENDER_EMAIL': os.environ.get('OEMS_EMAIL'),
    'APP_PASSWORD': os.environ.get('OEMS_EMAIL_PASSWORD'),
    'SMTP_SERVER': 'smtp.gmail.com',
    'SMTP_PORT': 587,
    'OTP_EXPIRY_MINUTES': 10,
    'MAX_OTP_ATTEMPTS': 3,
    'RATE_LIMIT_MINUTES': 5
}

# Startup pe check karo — production mein crash fast
if not EMAIL_CONFIG['SENDER_EMAIL'] or not EMAIL_CONFIG['APP_PASSWORD']:
    raise RuntimeError(
        "OEMS_EMAIL aur OEMS_EMAIL_PASSWORD .env mein set nahi hain! "
        ".env.example file dekho."
    )


def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, str(email)) is not None


def sanitize_input(data):
    if isinstance(data, str):
        return data.strip()
    return data


def rate_limit(max_attempts=3, window_minutes=5):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_ip = request.remote_addr
            key = f"rate_limit_{client_ip}_{f.__name__}"
            now = datetime.now()
            if key not in session:
                session[key] = {'count': 0, 'first_attempt': now.isoformat()}
            attempt_data = session[key]
            first_attempt = datetime.fromisoformat(attempt_data['first_attempt'])
            if now - first_attempt > timedelta(minutes=window_minutes):
                session[key] = {'count': 0, 'first_attempt': now.isoformat()}
                attempt_data = session[key]
            if attempt_data['count'] >= max_attempts:
                remaining = window_minutes - (now - first_attempt).seconds // 60
                raise TooManyRequests(f"Too many attempts. Try again in {remaining} minutes.")
            attempt_data['count'] += 1
            session[key] = attempt_data
            return f(*args, **kwargs)
        return decorated_function
    return decorator


class OTPManager:
    @staticmethod
    def generate_otp():
        return ''.join([str(secrets.randbelow(10)) for _ in range(6)])

    @staticmethod
    def store_otp(email, otp, mode='email', user_name=None):
        expiry_time = datetime.now() + timedelta(minutes=EMAIL_CONFIG['OTP_EXPIRY_MINUTES'])
        session['otp_data'] = {
            'otp': otp,
            'email': email,
            'mode': mode,
            'user_name': user_name,
            'expires_at': expiry_time.isoformat(),
            'attempts': 0,
            'created_at': datetime.now().isoformat()
        }

    @staticmethod
    def verify_otp(user_otp):
        if 'otp_data' not in session:
            return False, "No OTP found. Please request a new one."
        otp_data = session['otp_data']
        now = datetime.now()
        expires_at = datetime.fromisoformat(otp_data['expires_at'])
        if now > expires_at:
            session.pop('otp_data', None)
            return False, "OTP has expired. Please request a new one."
        if otp_data['attempts'] >= EMAIL_CONFIG['MAX_OTP_ATTEMPTS']:
            session.pop('otp_data', None)
            return False, "Too many failed attempts. Please request a new OTP."
        otp_data['attempts'] += 1
        session['otp_data'] = otp_data
        if str(user_otp) != otp_data['otp']:
            remaining = EMAIL_CONFIG['MAX_OTP_ATTEMPTS'] - otp_data['attempts']
            return False, f"Invalid OTP. {remaining} attempts remaining."
        session.pop('otp_data', None)
        return True, otp_data


class EmailService:
    def __init__(self):
        self.sender_email = EMAIL_CONFIG['SENDER_EMAIL']
        self.app_password = EMAIL_CONFIG['APP_PASSWORD']

    def _create_connection(self):
        try:
            server = smtplib.SMTP(EMAIL_CONFIG['SMTP_SERVER'], EMAIL_CONFIG['SMTP_PORT'])
            server.starttls()
            server.login(self.sender_email, self.app_password)
            return server
        except Exception as e:
            logger.error(f"SMTP Connection failed: {str(e)}")
            raise

    def send_otp_email(self, receiver_email, otp, mode="email", user_name="Student"):
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            display_name = sanitize_input(user_name) if user_name else "Student"
            msg = MIMEMultipart('alternative')
            msg['From'] = formataddr(('OEMS Support', self.sender_email))
            msg['To'] = receiver_email
            if mode == "password":
                msg['Subject'] = 'OEMS Account - Password Reset Request'
                action_text = "reset the password for your OEMS account"
                warning_text = "If you did not request a password reset, please ignore this email."
            else:
                msg['Subject'] = 'OEMS Account - Verify Your New Email'
                action_text = "update the email address associated with your OEMS account"
                warning_text = "If you did not request an email change, please ignore this email."

            text_content = f"Hi {display_name},\n\nYour OTP: {otp}\nValid for {EMAIL_CONFIG['OTP_EXPIRY_MINUTES']} minutes.\n\nOEMS Support"
            html_content = f"""<html><body style="font-family:Arial;background:#f4f5f7;padding:15px;">
                <table align="center" width="100%" style="max-width:500px;background:#fff;border-radius:6px;border:1px solid #e2e8f0;margin:0 auto;">
                <tr><td style="background:#e6f4ea;padding:15px 20px;text-align:center;border-bottom:1px solid #d1e8da;">
                <h2 style="margin:0;color:#1e293b;font-size:18px;">OEMS Security Update</h2></td></tr>
                <tr><td style="padding:20px;">
                <p>Hi <b>{display_name}</b>,</p>
                <p>We received a request to {action_text}.</p>
                <p style="font-weight:bold;">Your OTP:</p>
                <table width="100%"><tr><td align="center" style="background:#f8fafc;padding:12px;border-radius:4px;border:1px dashed #cbd5e1;">
                <span style="font-family:monospace;font-size:26px;font-weight:bold;letter-spacing:6px;">{otp}</span>
                </td></tr></table>
                <p style="margin-top:15px;font-size:13px;color:#888;">Valid for {EMAIL_CONFIG['OTP_EXPIRY_MINUTES']} minutes. {warning_text}</p>
                <p><strong>OEMS Support Team</strong><br><small>Ref: {current_time}</small></p>
                </td></tr></table></body></html>"""

            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))
            with self._create_connection() as server:
                server.sendmail(self.sender_email, receiver_email, msg.as_string())
            logger.info(f"OTP email sent to {receiver_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send OTP email: {str(e)}")
            return False

    def send_success_email(self, receiver_email, mode, user_name="Student"):
        try:
            display_name = sanitize_input(user_name) if user_name else "Student"
            msg = MIMEMultipart('alternative')
            msg['From'] = formataddr(('OEMS Support', self.sender_email))
            msg['To'] = receiver_email
            if mode == 'password':
                msg['Subject'] = "OEMS Account - Password Updated Successfully"
                message = "Your password has been successfully changed."
            else:
                msg['Subject'] = "OEMS Account - Email Updated Successfully"
                message = "Your email address has been successfully updated."

            text_content = f"Hi {display_name},\n\n{message}\n\nOEMS Support"
            html_content = f"""<html><body style="font-family:Arial;background:#f4f5f7;padding:15px;">
                <table align="center" width="100%" style="max-width:500px;background:#fff;border-radius:6px;border:1px solid #e2e8f0;margin:0 auto;">
                <tr><td style="background:#e6f4ea;padding:15px 20px;text-align:center;">
                <h2 style="margin:0;color:#1e293b;">Update Successful</h2></td></tr>
                <tr><td style="padding:20px;"><p>Hi <b>{display_name}</b>,</p><p>{message}</p>
                <p><strong>OEMS Support Team</strong></p></td></tr></table></body></html>"""

            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))
            with self._create_connection() as server:
                server.sendmail(self.sender_email, receiver_email, msg.as_string())
            return True
        except Exception as e:
            logger.error(f"Failed to send success email: {str(e)}")
            return False

    def create_exam_alert_msg(self, receiver_email, student_name, exam_name, exam_date, duration):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        display_name = sanitize_input(student_name) if student_name else "Student"
        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr(('OEMS Examination Control', self.sender_email))
        msg['To'] = receiver_email
        msg['Subject'] = f"New Exam Scheduled: {exam_name}"
        text_content = f"Hi {display_name},\n\nExam '{exam_name}' scheduled.\nDate: {exam_date}\nDuration: {duration} mins.\n\nOEMS"
        html_content = f"""<html><body style="font-family:Arial;background:#f4f5f7;padding:15px;">
            <table align="center" width="100%" style="max-width:500px;background:#fff;border-radius:6px;border:1px solid #e2e8f0;margin:0 auto;">
            <tr><td style="background:#eff6ff;padding:15px 20px;text-align:center;">
            <h2 style="margin:0;color:#1e3a8a;">New Exam Scheduled</h2></td></tr>
            <tr><td style="padding:20px;"><p>Hi <b>{display_name}</b>,</p>
            <p>A new exam has been published for your batch:</p>
            <table width="100%" style="background:#f8fafc;border-radius:6px;border:1px solid #e2e8f0;padding:15px;">
            <tr><td><strong>Course:</strong></td><td>{exam_name}</td></tr>
            <tr><td><strong>Date:</strong></td><td>{exam_date}</td></tr>
            <tr><td><strong>Duration:</strong></td><td>{duration} minutes</td></tr>
            </table><p style="margin-top:15px;">Best of luck!</p>
            <p><strong>OEMS Examination Control</strong><br><small>Ref: {current_time}</small></p>
            </td></tr></table></body></html>"""
        msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))
        return msg

    def send_bulk_exam_alerts(self, student_list, exam_name, exam_date, duration):
        if not student_list:
            return {'success': False, 'message': 'No students to notify'}
        success_count = 0
        failed_emails = []
        try:
            with self._create_connection() as server:
                for student in student_list:
                    receiver_email = student.get('email')
                    student_name = student.get('name') or 'Student'
                    if not receiver_email or not is_valid_email(receiver_email):
                        failed_emails.append({'name': student_name, 'reason': 'Invalid email'})
                        continue
                    try:
                        msg = self.create_exam_alert_msg(receiver_email, student_name, exam_name, exam_date, duration)
                        server.sendmail(self.sender_email, receiver_email, msg.as_string())
                        success_count += 1
                    except Exception as e:
                        failed_emails.append({'name': student_name, 'email': receiver_email, 'reason': str(e)})
            return {'success': True, 'sent': success_count, 'failed': len(failed_emails)}
        except Exception as e:
            return {'success': False, 'message': str(e)}


email_service = EmailService()


def send_email_async(func, *args, **kwargs):
    def task():
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Async email task failed: {str(e)}")
    thread = threading.Thread(target=task)
    thread.daemon = True
    thread.start()
    return thread


# ---------------- OTP ROUTES ----------------
@app.route('/send_otp', methods=['POST'])
@rate_limit(max_attempts=5, window_minutes=5)
def send_otp():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400
        new_email = sanitize_input(data.get('email'))
        mode = data.get('mode', 'email')
        user_name = data.get('name') or data.get('student_name')
        if not new_email or not is_valid_email(new_email):
            return jsonify({"success": False, "message": "Valid email is required"}), 400
        if mode == 'email':
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT id FROM students WHERE email = %s", (new_email,))
                if cursor.fetchone():
                    return jsonify({"success": False, "message": "Email already registered to another account."}), 400
            finally:
                cursor.close()
                conn.close()
        if mode not in ['email', 'password']:
            return jsonify({"success": False, "message": "Invalid mode"}), 400
        otp = OTPManager.generate_otp()
        OTPManager.store_otp(new_email, otp, mode, user_name)
        send_email_async(email_service.send_otp_email, new_email, otp, mode, user_name)
        return jsonify({"success": True, "message": "OTP sent successfully"}), 200
    except TooManyRequests as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except Exception as e:
        logger.error(f"Error in send_otp: {str(e)}")
        return jsonify({"success": False, "message": "Internal server error"}), 500


@app.route('/verify_otp', methods=['POST'])
@rate_limit(max_attempts=5, window_minutes=5)
def verify_otp():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400
        user_otp = sanitize_input(data.get('otp'))
        mode = data.get('mode')
        target_email = sanitize_input(data.get('email'))
        if not user_otp or not target_email or not is_valid_email(target_email):
            return jsonify({"success": False, "message": "OTP and valid email are required"}), 400
        is_valid, result = OTPManager.verify_otp(user_otp)
        if not is_valid:
            return jsonify({"success": False, "message": result}), 400
        otp_data = result
        if otp_data['email'] != target_email:
            return jsonify({"success": False, "message": "Email mismatch"}), 400
        user_name = otp_data.get('user_name', 'Student')
        send_email_async(email_service.send_success_email, target_email, mode or otp_data['mode'], user_name)
        return jsonify({"success": True, "message": "Verification successful", "verified_email": target_email}), 200
    except TooManyRequests as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except Exception as e:
        logger.error(f"Error in verify_otp: {str(e)}")
        return jsonify({"success": False, "message": "Internal server error"}), 500


@app.route('/resend_otp', methods=['POST'])
@rate_limit(max_attempts=3, window_minutes=10)
def resend_otp():
    try:
        data = request.get_json()
        email = sanitize_input(data.get('email'))
        if not email or not is_valid_email(email):
            return jsonify({"success": False, "message": "Valid email required"}), 400
        if 'otp_data' in session:
            created_at = datetime.fromisoformat(session['otp_data']['created_at'])
            if datetime.now() - created_at < timedelta(seconds=30):
                remaining = 30 - (datetime.now() - created_at).seconds
                return jsonify({"success": False, "message": f"Wait {remaining} seconds before requesting new OTP"}), 429
        old_data = session.get('otp_data', {})
        mode = old_data.get('mode', 'email')
        user_name = old_data.get('user_name', 'Student')
        otp = OTPManager.generate_otp()
        OTPManager.store_otp(email, otp, mode, user_name)
        send_email_async(email_service.send_otp_email, email, otp, mode, user_name)
        return jsonify({"success": True, "message": "New OTP sent"}), 200
    except TooManyRequests as e:
        return jsonify({"success": False, "message": str(e)}), 429
    except Exception as e:
        logger.error(f"Error in resend_otp: {str(e)}")
        return jsonify({"success": False, "message": "Internal server error"}), 500


@app.route('/send_bulk_exam_alerts', methods=['POST'])
def bulk_exam_alerts():
    try:
        data = request.get_json()
        for field in ['students', 'exam_name', 'exam_date', 'duration']:
            if field not in data:
                return jsonify({"success": False, "message": f"Missing field: {field}"}), 400
        student_list = data['students']
        if not isinstance(student_list, list) or len(student_list) == 0:
            return jsonify({"success": False, "message": "Student list must be non-empty"}), 400
        # Hamesha async bhejo
        send_email_async(
            email_service.send_bulk_exam_alerts,
            student_list, data['exam_name'], data['exam_date'], data['duration']
        )
        return jsonify({"success": True, "message": "Bulk alert started", "total_students": len(student_list)}), 202
    except Exception as e:
        logger.error(f"Error in bulk_exam_alerts: {str(e)}")
        return jsonify({"success": False, "message": "Internal server error"}), 500


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ---------------- RUN APP ----------------
if __name__ == "__main__":
    # Production mein debug=False ZAROOR karo
    app.run(debug=False)