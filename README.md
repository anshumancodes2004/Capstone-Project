# OEMS — Online Examination Management System

> A full-stack, AI-powered examination platform built for universities. Supports secure proctored exams, automated AI evaluation, plagiarism detection, and real-time violation monitoring.

-----

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [Exam Flow](#exam-flow)
- [AI Evaluation Engine](#ai-evaluation-engine)
- [AI Proctoring System](#ai-proctoring-system)
- [API Routes Reference](#api-routes-reference)
- [Email Notifications](#email-notifications)
- [Security Features](#security-features)
- [Screenshots](#screenshots)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)

-----

## Overview

OEMS (Online Examination Management System) is a production-grade web application designed for colleges and universities to conduct online exams with:

- **Role-based access** for Admins and Students
- **Three question types**: MCQ, MSQ (Multi-Select), and Theory
- **AI-powered answer evaluation** using Sentence-BERT (semantic similarity)
- **Automated plagiarism detection** using TF-IDF cosine similarity
- **Live AI proctoring** with face detection, gaze tracking, and phone detection (YOLOv8 + OpenCV)
- **Secure browser mode** via Electron (optional, campus-IP enforced)
- **Automated post-exam pipeline**: plagiarism → hold → evaluate → email PDF

-----

## Features

### Admin

- Create, publish, unpublish, and delete exams
- Add questions (MCQ / MSQ / Theory) with model answers
- Manage students — single add or bulk CSV upload
- View results dashboard with Hold / Release / Disqualify / Re-evaluate actions
- Trigger manual evaluation for any exam
- View plagiarism similarity report per exam
- View violation logs with timestamps, type badges, and filters
- Resend login credentials to any student

### Student

- Login with admission number and password
- View available exams with countdown timers
- Take exams in a secure, locked-down browser interface
- Randomised question order per session
- Real-time question navigation panel
- View result with question-wise score and AI feedback
- Download result PDF (emailed automatically after evaluation)
- Update email and password via OTP verification

### Evaluation Pipeline

- Exams submit into `AwaitingExamEnd` status — no immediate evaluation
- On exam end: plagiarism check runs on all theory answers
- Similarity ≥ 70% → result placed on **Hold**, hold email sent
- Clean students → SBERT semantic evaluation → PDF generated → result emailed
- Admin can manually trigger evaluation or re-evaluate individual results

### Proctoring

- Face detection using multi-cascade Haar classifiers (frontal + alt2 + profile)
- Gaze direction analysis (Looking Left / Right / Up / Down)
- YOLOv8-based mobile phone detection
- DevTools and tab-switch detection
- All violations stored in DB with timestamps
- Auto-terminate exam after 5 violations

-----

## Tech Stack

|Layer               |Technology                                  |
|--------------------|--------------------------------------------|
|Backend             |Python 3.x, Flask                           |
|Database            |MySQL (connection pooling)                  |
|AI Evaluation       |Sentence-BERT (`all-MiniLM-L6-v2`)          |
|Plagiarism Detection|TF-IDF + Cosine Similarity (scikit-learn)   |
|AI Proctoring       |OpenCV (Haar cascades), YOLOv8 (Ultralytics)|
|PDF Generation      |ReportLab                                   |
|Email               |SMTP (Gmail App Password)                   |
|Secure Browser      |Electron (optional)                         |
|Frontend            |Jinja2 templates, vanilla JS, CSS           |

-----

## Project Structure

```
oems/
├── app.py                      # Main Flask application (2200+ lines)
├── .env                        # Environment variables (not committed)
├── requirements.txt            # Python dependencies
├── yolov8n.pt                  # YOLOv8 nano model for phone detection
└── templates/
    ├── home.html
    ├── admin_login.html
    ├── student_login.html
    ├── admin_dashboard.html
    ├── student_dashboard.html
    ├── create_exam.html
    ├── add_question.html
    ├── edit_question.html
    ├── questions.html
    ├── add_student.html
    ├── student_manager.html
    ├── start_exam.html             # Secure exam interface (proctoring)
    ├── exam_submitted.html
    ├── already_submitted.html
    ├── results_summary.html        # Admin results dashboard
    ├── result_details.html
    ├── student_result.html
    ├── plagiarism.html
    ├── violation_logs.html
    ├── edit_profile.html
    ├── secure_browser_required.html
    └── campus_only.html
```

-----

## Database Schema

Run the following SQL to set up the database:

```sql
CREATE DATABASE exam_system;
USE exam_system;

CREATE TABLE admins (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    admin_id    VARCHAR(50) UNIQUE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    password    VARCHAR(255) NOT NULL,
    branch      VARCHAR(50) DEFAULT 'ALL'
);

CREATE TABLE students (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    admission_no  VARCHAR(50) UNIQUE NOT NULL,
    program       VARCHAR(50),
    branch        VARCHAR(50),
    semester      VARCHAR(10),
    email         VARCHAR(255),
    password      VARCHAR(255) NOT NULL
);

CREATE TABLE exams (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    title         VARCHAR(200) NOT NULL,
    exam_type     VARCHAR(20) DEFAULT 'theory',
    total_marks   INT,
    program       VARCHAR(50),
    branch        VARCHAR(50),
    semester      VARCHAR(10),
    start_time    DATETIME,
    duration      INT,
    status        VARCHAR(20) DEFAULT 'draft',
    browser_mode  VARCHAR(30) DEFAULT 'any',
    ai_proctoring TINYINT(1) DEFAULT 0
);

CREATE TABLE questions (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    exam_id       INT NOT NULL,
    question_text TEXT NOT NULL,
    question_type VARCHAR(20) DEFAULT 'theory',
    optionA       TEXT,
    optionB       TEXT,
    optionC       TEXT,
    optionD       TEXT,
    correct_answer TEXT,
    marks         INT DEFAULT 5,
    FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
);

CREATE TABLE answers (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    student_id    INT NOT NULL,
    exam_id       INT NOT NULL,
    question_id   INT NOT NULL,
    answer        TEXT,
    score         FLOAT DEFAULT NULL,
    feedback      TEXT,
    FOREIGN KEY (student_id)  REFERENCES students(id)  ON DELETE CASCADE,
    FOREIGN KEY (exam_id)     REFERENCES exams(id)     ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE TABLE results (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    student_id        INT NOT NULL,
    exam_id           INT NOT NULL,
    total_score       FLOAT DEFAULT 0,
    submission_status VARCHAR(50) DEFAULT 'AwaitingExamEnd',
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id)    REFERENCES exams(id)    ON DELETE CASCADE
);

CREATE TABLE exam_violations (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    student_id     INT NOT NULL,
    exam_id        INT NOT NULL,
    violation_type VARCHAR(100) NOT NULL,
    details        TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (exam_id)    REFERENCES exams(id)    ON DELETE CASCADE
);
```

-----

## Installation

### Prerequisites

- Python 3.9+
- MySQL 8.0+
- Node.js (optional, for Electron secure browser)

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/oems.git
cd oems
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

**requirements.txt:**

```
flask
mysql-connector-python
werkzeug
python-dotenv
scikit-learn
sentence-transformers
reportlab
ultralytics
opencv-python
requests
```

### 4. Set up the database

```bash
mysql -u root -p < schema.sql
```

### 5. Download YOLOv8 model

```bash
# Auto-downloads on first run, or manually:
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

### 6. SBERT model (downloads automatically on first evaluation)

```bash
# First evaluation run will download ~80MB model
# all-MiniLM-L6-v2 from HuggingFace
```

-----

## Environment Variables

Create a `.env` file in the project root:

```env
# Flask
SECRET_KEY=your_random_secret_key_here

# Database
DB_HOST=localhost
DB_USER=root
DB_PASS=your_mysql_password
DB_NAME=exam_system

# Email (Gmail App Password)
OEMS_EMAIL=your_email@gmail.com
OEMS_EMAIL_PASSWORD=your_gmail_app_password

# AI Evaluation
SBERT_MODEL=all-MiniLM-L6-v2

# Campus IP Ranges (comma-separated prefixes for secure browser enforcement)
CAMPUS_IP_RANGES=10.104.242,192.168.1.
```

> **Gmail App Password Setup:** Go to Google Account → Security → 2-Step Verification → App Passwords. Generate a password for “Mail”.

-----

## Running the Application

```bash
python app.py
```

Server starts at `http://127.0.0.1:5000`

**Default Admin Setup** (insert manually into DB):

```sql
INSERT INTO admins (admin_id, name, password, branch)
VALUES ('ADMIN001', 'Admin Name',
        '<werkzeug_hashed_password>', 'ALL');
```

Generate a hashed password:

```python
from werkzeug.security import generate_password_hash
print(generate_password_hash("your_admin_password"))
```

-----

## Exam Flow

```
Admin creates exam (draft)
        ↓
Admin adds questions (MCQ / MSQ / Theory with model answers)
        ↓
Admin publishes exam → bulk email alert to eligible students
        ↓
Student logs in → sees available exam with countdown timer
        ↓
Student starts exam → Gatekeeper screen (camera check if proctored)
        ↓
Student submits answers → status = "AwaitingExamEnd"
(No evaluation happens yet)
        ↓
Exam end time passes (or admin triggers manually)
        ↓
Step 1: Force-submit students who started but didn't submit
        ↓
Step 2: TF-IDF Plagiarism Check (theory answers)
  ├─ similarity ≥ 70% → status = "Hold" → hold email sent
  └─ similarity < 70% → proceed to evaluation
        ↓
Step 3: SBERT AI Evaluation
  → score each theory answer
  → calculate total
  → generate PDF report
  → send result email with PDF attachment
        ↓
Admin actions available:
  ├─ Hold → "Release" (re-evaluates) or "Disqualify" (score = 0)
  └─ Evaluated → "Re-evaluate" (resets and re-runs SBERT)
```

-----

## AI Evaluation Engine

OEMS uses **Sentence-BERT** (`all-MiniLM-L6-v2`) for semantic similarity-based answer evaluation.

### How it works

1. **Quality Guard** — Pre-filter before SBERT runs:
- Too short (< 10 chars or < 5 tokens) → 0 marks
- Keyword stuffing detected → 0 marks
- Comma-separated keyword list with no sentence endings → 0 marks
- **Important:** Answers with sentence-ending punctuation (`.`, `!`, `?`) bypass list checks — prevents false negatives on academic writing style
1. **SBERT Semantic Scoring:**
   
   ```
   similarity = cosine_similarity(
       encode(model_answer),
       encode(student_answer)
   )
   ```
- Applies length factor (student answer must cover ≥35% of reference length)
- Similarity < 30% → 0 marks
- Otherwise: `score = similarity × length_factor × max_marks` (rounded to 0.5 steps)
1. **Feedback generation** based on similarity percentage:
- ≥ 80% → “Excellent answer with strong semantic match”
- ≥ 65% → “Good answer with minor missing points”
- ≥ 45% → “Partial answer; key explanation is incomplete”
- < 45% → “Weak answer; limited semantic match”

### Why not an LLM?

- LLMs like deepseek-r1 spend tokens on reasoning (`<think>` blocks), causing output truncation before `SCORE:` line → always returns 0
- SBERT is deterministic, fast (~50-100ms/answer on CPU), and produces consistent results
- No GPU required, MacBook-friendly

-----

## AI Proctoring System

Activated per-exam via `ai_proctoring = 1` setting. Captures webcam frames every 3 seconds.

### Detection Pipeline (per frame)

```
Frame captured (320×240 JPEG)
        ↓
Step 1: YOLOv8 phone detection (conf=0.28)
  → "cell phone" / "mobile" detected → immediate violation
        ↓
Step 2: Multi-cascade face detection (CLAHE preprocessed)
  → Pass 1: Haar frontal default (minNeighbors=5)
  → Pass 2: Haar alt2 cascade
  → IoU deduplication
  → Pass 3: Profile cascade ONLY if frontal = 0 faces
             (prevents false "multiple faces" on head turns)
        ↓
Step 3: Face count check
  → 0 faces → "Face not visible"
  → > 1 face → "Multiple people detected"
        ↓
Step 4: Eye detection on face ROI (minNeighbors=4)
  → 0 eyes → "Eyes not visible"
        ↓
Step 5: Gaze direction (face centre offset)
  → |x_offset| > 0.40 → "Looking Left/Right"
  → |y_offset| > 0.40 → "Looking Up/Down"
```

### Violation Counting

- Phone detection → **immediate violation** (no grace period)
- Face/gaze issues → **3 consecutive frames** before counting as 1 violation
- 5 violations → **exam auto-terminated**, force-submitted
- All violations stored in `exam_violations` table

-----

## API Routes Reference

### Auth

|Route           |Method   |Description  |
|----------------|---------|-------------|
|`/`             |GET      |Home page    |
|`/admin_login`  |GET, POST|Admin login  |
|`/student_login`|GET, POST|Student login|
|`/logout`       |GET      |Clear session|

### Admin — Exam Management

|Route                           |Method   |Description           |
|--------------------------------|---------|----------------------|
|`/admin`                        |GET      |Admin dashboard       |
|`/create_exam`                  |GET, POST|Create new exam       |
|`/add_question/<exam_id>`       |GET, POST|Add question to exam  |
|`/edit_question/<question_id>`  |GET, POST|Edit question         |
|`/delete_question/<question_id>`|POST     |Delete question       |
|`/delete_exam/<exam_id>`        |POST     |Delete exam + all data|
|`/publish_exam/<exam_id>`       |GET      |Publish + email alert |
|`/unpublish_exam/<exam_id>`     |GET      |Unpublish exam        |
|`/questions/<exam_id>`          |GET      |View exam questions   |

### Admin — Student Management

|Route                             |Method   |Description           |
|----------------------------------|---------|----------------------|
|`/student_manager`                |GET      |List all students     |
|`/add_student`                    |GET, POST|Add single or bulk CSV|
|`/delete_student/<id>`            |POST     |Delete student        |
|`/resend_credentials/<student_id>`|POST     |Resend login email    |

### Admin — Results & Evaluation

|Route                                      |Method|Description              |
|-------------------------------------------|------|-------------------------|
|`/results`                                 |GET   |Results dashboard        |
|`/result_details/<student_id>/<exam_id>`   |GET   |Per-question scores      |
|`/trigger_exam_evaluation/<exam_id>`       |POST  |Manual evaluation trigger|
|`/release_result/<student_id>/<exam_id>`   |POST  |Release held result      |
|`/disqualify_result/<student_id>/<exam_id>`|POST  |Disqualify student       |
|`/run_ai_check`                            |GET   |Manual AI evaluation run |
|`/reset_ai_evaluation`                     |GET   |Reset all theory scores  |
|`/plagiarism/<exam_id>`                    |GET   |View plagiarism report   |

### Admin — Violations

|Route            |Method|Description                |
|-----------------|------|---------------------------|
|`/violation_logs`|GET   |All violations (searchable)|

### Student

|Route                   |Method   |Description          |
|------------------------|---------|---------------------|
|`/student`              |GET      |Student dashboard    |
|`/start_exam/<exam_id>` |GET      |Load exam interface  |
|`/submit_exam/<exam_id>`|POST     |Submit answers       |
|`/my_result/<exam_id>`  |GET      |View own result      |
|`/edit_profile`         |GET, POST|Update email/password|

### System

|Route             |Method|Description              |
|------------------|------|-------------------------|
|`/detect_cheating`|POST  |Proctoring frame analysis|
|`/log_violation`  |POST  |Store violation from JS  |
|`/send_otp`       |POST  |Send OTP email           |
|`/verify_otp`     |POST  |Verify OTP               |
|`/resend_otp`     |POST  |Resend OTP               |

-----

## Email Notifications

All emails sent via Gmail SMTP with HTML formatting.

|Trigger                           |Email Type                              |
|----------------------------------|----------------------------------------|
|Student added / credentials resent|Welcome email with login details        |
|Exam published                    |Bulk exam alert to all eligible students|
|Exam evaluated (clean result)     |Result email with PDF attachment        |
|Result placed on hold             |Hold notice with plagiarism reason      |
|Password / email change           |OTP verification email                  |
|Update confirmed                  |Success confirmation email              |

-----

## Security Features

- **Passwords** hashed with Werkzeug `pbkdf2:sha256`
- **Session-based auth** with role checks (`admin` / `student`)
- **CSRF protection** via Flask sessions
- **Rate limiting** on OTP endpoints (max 5 attempts / 5 min)
- **OTP expiry** — 10 minutes, max 3 verification attempts
- **Browser mode enforcement:**
  - `any` — any browser allowed
  - `secure_any` — requires Electron secure browser
  - `secure_campus` — requires Electron + campus IP range
- **Content Security Policy** header in exam page
- **Double-submission prevention** — DB check before answer insert
- **Exam time validation** — server-side start/end enforcement
- **DB connection pooling** (pool size 10) — prevents connection exhaustion

-----

## Submission Status Values

|Status           |Meaning                                      |
|-----------------|---------------------------------------------|
|`AwaitingExamEnd`|Submitted, waiting for exam end processor    |
|`Pending`        |Evaluation in progress or partially failed   |
|`Evaluated`      |AI evaluation complete, email sent           |
|`Hold`           |Flagged for plagiarism, awaiting admin review|
|`Disqualified`   |Admin disqualified, score forced to 0        |

-----

## Known Limitations

- SBERT model downloads ~80MB on first run (requires internet)
- YOLOv8 phone detection accuracy depends on lighting and angle
- Proctoring only works with a webcam; no fallback for absent camera
- Email delivery depends on Gmail App Password being valid
- Bulk exam alerts may hit Gmail rate limits for very large batches
- Electron secure browser must be built separately (not included in this repo)

-----

## Contributing

1. Fork the repository
1. Create a feature branch: `git checkout -b feature/your-feature`
1. Commit your changes: `git commit -m "Add your feature"`
1. Push to the branch: `git push origin feature/your-feature`
1. Open a Pull Request

-----

## License

This project is licensed under the MIT License. See <LICENSE> for details.

-----

## Author

Developed as a final-year B.Tech project for Galgotias University.  
Stack: Flask · MySQL · Sentence-BERT · OpenCV · YOLOv8 · ReportLab · Electron
