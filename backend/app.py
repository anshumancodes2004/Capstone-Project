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
import google.generativeai as genai


# ============================================================
# .env se saari secrets load karo
# ============================================================
load_dotenv()

# ============================================================
# Gemini 2.5 Flash (API)
# ============================================================
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel("gemini-2.5-flash")

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
    student_id = session.get("student_id")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM results WHERE student_id=%s AND exam_id=%s", (student_id, exam_id))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return """
        <div style="text-align:center; padding:50px; font-family:sans-serif;">
            <h2 style="color:#dc3545;">You have already submitted this exam! 🚫</h2>
            <a href="/student" style="text-decoration:none; color:#4f46e5;">Go to Dashboard</a>
        </div>
        """, 400

    cursor.execute("SELECT * FROM questions WHERE exam_id=%s", (exam_id,))
    questions = cursor.fetchall()

    total_score = 0
    exam_status = "Evaluated"

    for q in questions:
        if q["question_type"] == "mcq":
            student_answer = answers_data.get(f"q{q['id']}", "").strip()
            if student_answer == q["correct_answer"]:
                score = q["marks"]
                feedback = "Correct answer"
            else:
                score = 0
                feedback = "Incorrect or No answer"
            total_score += score
            cursor.execute("""
                INSERT INTO answers (student_id, exam_id, question_id, answer, score, feedback)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (student_id, exam_id, q["id"], student_answer, score, feedback))

        elif q["question_type"] == "msq":
            student_answers_list = answers_data.getlist(f"q{q['id']}")
            student_answers_list.sort()
            student_answer = ", ".join(student_answers_list)

            if q["correct_answer"]:
                db_correct_answers = [ans.strip() for ans in q["correct_answer"].split(",")]
                db_correct_answers.sort()
                db_correct_str = ", ".join(db_correct_answers)
            else:
                db_correct_str = ""

            if student_answer == db_correct_str and len(student_answer) > 0:
                score = q["marks"]
                feedback = "Correct answers"
            else:
                score = 0
                feedback = "Incorrect or Partially Correct"

            total_score += score
            cursor.execute("""
                INSERT INTO answers (student_id, exam_id, question_id, answer, score, feedback)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (student_id, exam_id, q["id"], student_answer, score, feedback))

        else:
            student_answer = answers_data.get(f"q{q['id']}", "").strip()
            score = None
            feedback = "Pending Evaluation"
            exam_status = "Pending"
            cursor.execute("""
                INSERT INTO answers (student_id, exam_id, question_id, answer, score, feedback)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (student_id, exam_id, q["id"], student_answer, score, feedback))

    cursor.execute("""
        INSERT INTO results (student_id, exam_id, total_score, submission_status)
        VALUES (%s, %s, %s, %s)
    """, (student_id, exam_id, round(total_score, 2), exam_status))

    conn.commit()
    cursor.close()
    conn.close()

    return f"""
    <div style="text-align:center; padding:50px; font-family:Poppins, sans-serif;">
        <h2 style="color:#22c55e;">Exam Submitted Successfully ✅</h2>
        <p style="font-size:1.2rem; color:#555;">Your Objective Score: <b>{round(total_score, 2)}</b></p>
        <p style="font-size:0.9rem; color:#888;">(Theory questions will be evaluated shortly)</p>
        <hr style="width:200px; margin:20px auto;">
        <a href="/student" style="text-decoration:none; color:#4f46e5; font-weight:bold;">Go to Dashboard</a>
    </div>
    """


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


# ---------------- AI EVALUATION HELPER ----------------
def evaluate_answer(question, student_answer, max_marks):
    """
    Gemini 2.5 Flash se theory answer evaluate karo.
    Returns: (score, feedback)
    """
 
    # Bahut chota ya irrelevant answer — Gemini call bhi mat karo
    if not student_answer or len(student_answer.strip()) < 20:
        return 0, "Answer too short or not provided."
 
    word_count = len(student_answer.split())
    if word_count < 5:
        return 0, "Answer too short to evaluate."
 
    prompt = f"""You are a strict university exam evaluator.
 
Question: {question}
 
Student Answer: {student_answer}
 
Rules:
1. If the answer is completely unrelated to the question, give Score: 0
2. If the answer is random text, a name, or gibberish, give Score: 0
3. If the answer is too short (less than 5 words), give Score: 0
4. Award marks proportionally based on how correctly and completely the concept is explained.
5. Score must be a number between 0 and {max_marks}. No decimals above 0.5 steps.
6. Be strict but fair.
 
Respond in EXACTLY this format (nothing else):
Score: <number>
Feedback: <one sentence reason>"""
 
    try:
        response = gemini_model.generate_content(prompt)
        result   = response.text.strip()
 
        # Score parse karo
        score_match    = re.search(r'Score:\s*(\d+(\.\d+)?)', result)
        feedback_match = re.search(r'Feedback:\s*(.*)', result)
 
        score    = float(score_match.group(1))    if score_match    else 0
        feedback = feedback_match.group(1).strip() if feedback_match else "Evaluated"
 
        # Score ko max_marks se cap karo — Gemini kabhi kabhi zyada de deta hai
        score = min(score, float(max_marks))
        score = max(score, 0)
 
    except Exception as e:
        print(f"Gemini evaluation error: {e}")
        score    = 0
        feedback = "AI evaluation failed — please re-run."
 
    return score, feedback


# ---------------- AI CHECKING ROUTE ----------------
import time
 
@app.route("/run_ai_check")
@login_required("admin")
def run_ai_check():
 
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
 
    # Sirf theory questions jo evaluate nahi hue
    cursor.execute("""
        SELECT answers.id, answers.answer,
               questions.question_text, questions.marks
        FROM answers
        JOIN questions ON answers.question_id = questions.id
        WHERE answers.score IS NULL
        AND questions.question_type = 'theory'
    """)
    records = cursor.fetchall()
 
    print(f"[Gemini] Total pending theory answers: {len(records)}")
 
    evaluated = 0
    failed    = 0
 
    for i, r in enumerate(records):
        question       = r["question_text"]
        student_answer = r["answer"]
        max_marks      = r["marks"]
 
        # Khali answer — Gemini call mat karo
        if not student_answer or len(student_answer.strip()) < 20:
            cursor.execute(
                "UPDATE answers SET score=%s, feedback=%s WHERE id=%s",
                (0, "No answer submitted or answer too short.", r["id"])
            )
            evaluated += 1
            continue
 
        score, feedback = evaluate_answer(question, student_answer, max_marks)
 
        print(f"[Gemini] Answer #{r['id']} → Score: {score}/{max_marks}")
 
        cursor.execute(
            "UPDATE answers SET score=%s, feedback=%s WHERE id=%s",
            (round(score, 1), feedback, r["id"])
        )
        evaluated += 1
 
        # ── Rate limiting: 10 RPM = max 10 requests/minute ──
        # Har 10 requests ke baad 65 seconds wait karo
        if (i + 1) % 10 == 0 and (i + 1) < len(records):
            print(f"[Gemini] Rate limit pause — 65s wait ({i+1}/{len(records)} done)")
            time.sleep(65)
 
    conn.commit()
    cursor.close()
    conn.close()
 
    print(f"[Gemini] Evaluation complete — {evaluated} evaluated, {failed} failed")
    return f"AI Evaluation Complete — {evaluated} answers evaluated."


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