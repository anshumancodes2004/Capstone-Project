Flask==3.0.2
mysql-connector-python==8.3.0
werkzeug==3.0.1
python-dotenv==1.0.1
sentence-transformers==2.5.1
scikit-learn==1.4.1.post1
numpy==1.26.4
opencv-python==4.9.0.80
ultralytics==8.1.29
reportlab==4.1.0

CREATE DATABASE IF NOT EXISTS exam_system;
USE exam_system;

-- 1. Admins Table
CREATE TABLE IF NOT EXISTS admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    password VARCHAR(255) NOT NULL,
    branch VARCHAR(50) NOT NULL -- 'ALL' or specific branch like 'BCA'
) ENGINE=InnoDB;

-- 2. Students Table
CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admission_no VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    program VARCHAR(100) NOT NULL,
    branch VARCHAR(50) NOT NULL,
    semester VARCHAR(20) NOT NULL,
    email VARCHAR(100) UNIQUE,
    password VARCHAR(255) NOT NULL
) ENGINE=InnoDB;

-- 3. Exams Table
CREATE TABLE IF NOT EXISTS exams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(150) NOT NULL,
    exam_type VARCHAR(20) NOT NULL, -- 'theory' or 'objective'
    total_marks INT NOT NULL,
    program VARCHAR(100) NOT NULL,
    branch VARCHAR(50) NOT NULL,
    semester VARCHAR(20) NOT NULL,
    start_time DATETIME NOT NULL,
    duration INT NOT NULL, -- in minutes
    status VARCHAR(20) DEFAULT 'draft', -- 'draft' or 'publish'
    browser_mode VARCHAR(20) DEFAULT 'any', -- 'any', 'secure_any', 'secure_campus'
    ai_proctoring TINYINT(1) DEFAULT 0
) ENGINE=InnoDB;

-- 4. Questions Table
CREATE TABLE IF NOT EXISTS questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    exam_id INT NOT NULL,
    question_text TEXT NOT NULL,
    question_type VARCHAR(10) NOT NULL, -- 'theory', 'mcq', 'msq'
    optionA TEXT DEFAULT NULL,
    optionB TEXT DEFAULT NULL,
    optionC TEXT DEFAULT NULL,
    optionD TEXT DEFAULT NULL,
    correct_answer TEXT NOT NULL, -- Options joined by comma for MSQ, outline text for Theory
    marks INT NOT NULL,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 5. Results Table
CREATE TABLE IF NOT EXISTS results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    exam_id INT NOT NULL,
    total_score DECIMAL(5,2) DEFAULT 0.00,
    submission_status VARCHAR(30) DEFAULT 'AwaitingExamEnd', -- 'AwaitingExamEnd', 'Pending', 'Evaluated', 'Hold', 'Disqualified'
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_student_exam (student_id, exam_id),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 6. Answers Table
CREATE TABLE IF NOT EXISTS answers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    exam_id INT NOT NULL,
    question_id INT NOT NULL,
    answer TEXT,
    score DECIMAL(5,2) DEFAULT NULL, -- NULL means evaluation pending
    feedback TEXT,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 7. Exam Violations (Proctoring Log) Table
CREATE TABLE IF NOT EXISTS exam_violations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    exam_id INT NOT NULL,
    violation_type VARCHAR(100) NOT NULL, -- 'Mobile phone detected', 'Looking Left', etc.
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
) ENGINE=InnoDB;
