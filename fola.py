import os
import io
import mimetypes
from functools import wraps

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
    send_file,
)

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from supabase import create_client
from dotenv import load_dotenv


load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-key"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SUPABASE_BUCKET = "school files"

MASTER_ADMIN_NAME = os.environ.get(
    "MASTER_ADMIN_NAME",
    "Admin"
)

MASTER_ADMIN_PASSWORD = os.environ.get(
    "MASTER_ADMIN_PASSWORD",
    "admin123"
)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured.")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not configured.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is not configured.")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


ALLOWED_RESULT_EXTENSIONS = {
    ".pdf",
    ".ods",
    ".xlsx",
    ".xls",
    ".csv",
}

ALLOWED_NOTE_EXTENSIONS = {
    ".pdf",
    ".ods",
    ".xlsx",
    ".xls",
    ".csv",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".txt",
}


def get_db():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def fetch_one(query, params=()):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()


def fetch_all(query, params=()):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def execute(query, params=()):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()


def initialize_database():
    statements = [
        """
        CREATE TABLE IF NOT EXISTS students (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT 'General',
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS teachers (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS admins (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_admins_name_lower
        ON admins (LOWER(name));        """,
        """
        CREATE TABLE IF NOT EXISTS subjects (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT 'General',
            term TEXT NOT NULL,
            note_path TEXT,
            note_filename TEXT,
            mime_type TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS results (
            id BIGSERIAL PRIMARY KEY,
            student_id BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            term TEXT NOT NULL,
            filename TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            mime_type TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS news (
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_students_name
        ON students (LOWER(name))
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_teachers_name
        ON teachers (LOWER(name))
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_admins_name
        ON admins (LOWER(name))
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_subjects_group
        ON subjects (
            LOWER(class_name),
            LOWER(department),
            LOWER(term)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_results_student_term
        ON results (
            student_id,
            term,
            created_at DESC
        )
        """,
    ]

    with get_db() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)

            cur.execute("""
                ALTER TABLE results
                DROP CONSTRAINT IF EXISTS results_student_id_fkey
            """)

            cur.execute("""
                ALTER TABLE results
                ADD CONSTRAINT results_student_id_fkey
                FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_admins_name_lower
                ON admins (LOWER(name))
            """)

        conn.commit()


def storage_upload(path, file_bytes, mime_type):
    try:
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path,
            file_bytes,
            {
                "content-type": mime_type or "application/octet-stream",
                "upsert": "true",
            }
        )
        return True
    except Exception as e:
        print("Storage upload error:", e)
        return False


def storage_delete(path):
    if not path:
        return

    try:
        supabase.storage.from_(SUPABASE_BUCKET).remove([path])
    except Exception as e:
        print("Storage delete error:", e)


def get_signed_url(path):
    if not path:
        return None

    try:
        result = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(
            path,
            3600
        )

        if isinstance(result, dict):
            return (
                result.get("signedURL")
                or result.get("signedUrl")
                or result.get("signed_url")
            )

    except Exception as e:
        print("Signed URL error:", e)

    return None


def login_required(role=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "role" not in session:
                flash("Please log in first.", "error")
                return redirect(url_for("login"))

            if role and session.get("role") != role:
                abort(403)

            return func(*args, **kwargs)

        return wrapper

    return decorator


def current_user():
    role = session.get("role")

    if role == "student":
        student = fetch_one(
            """
            SELECT id, name, class_name, department
            FROM students
            WHERE id = %s
            """,
            (session.get("user_id"),)
        )

        if student:
            return student

    elif role == "teacher":
        teacher = fetch_one(
            """
            SELECT id, name
            FROM teachers
            WHERE id = %s
            """,
            (session.get("user_id"),)
        )

        if teacher:
            return teacher

    elif role == "admin":
        if session.get("admin_type") == "master":
            return {
                "id": "master",
                "name": MASTER_ADMIN_NAME,
                "is_master": True
            }

        admin = fetch_one(
            """
            SELECT id, name
            FROM admins
            WHERE id = %s
            """,
            (session.get("user_id"),)
        )

        if admin:
            admin["is_master"] = False
            return admin

    return None


def normalize_name(name):
    return " ".join(name.strip().split())


def normalize_department(department):
    department = department.strip()

    if not department:
        return "General"

    return department


def normalize_term(term):
    allowed = {
        "First Term",
        "Second Term",
        "Third Term"
    }

    if term not in allowed:
        return None

    return term


def get_file_extension(filename):
    return os.path.splitext(filename.lower())[1]


def render_spreadsheet(file_bytes, filename):
    extension = get_file_extension(filename)

    if extension == ".csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
    elif extension == ".ods":
        df = pd.read_excel(
            io.BytesIO(file_bytes),
            engine="odf"
        )
    elif extension in {".xlsx", ".xlsm"}:
        df = pd.read_excel(
            io.BytesIO(file_bytes),
            engine="openpyxl"
        )
    elif extension == ".xls":
        df = pd.read_excel(
            io.BytesIO(file_bytes),
            engine="xlrd"
        )
    else:
        return None

    return df.fillna("").to_html(
        classes="result-table",
        index=False,
        border=0
    )


@app.route("/")
def index():
    if "role" not in session:
        return redirect(url_for("login"))

    role = session.get("role")

    if role == "student":
        return redirect(url_for("student_dashboard"))

    if role == "teacher":
        return redirect(url_for("teacher_dashboard"))

    if role == "admin":
        return redirect(url_for("admin_dashboard"))

    session.clear()
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role", "").strip().lower()
        name = normalize_name(request.form.get("name", ""))
        password = request.form.get("password", "")

        if not name or not password:
            flash("Please enter your name and password.", "error")
            return redirect(url_for("login"))

        if role == "student":
            student = fetch_one(
                """
                SELECT *
                FROM students
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if student and check_password_hash(
                student["password_hash"],
                password
            ):
                session.clear()
                session["role"] = "student"
                session["user_id"] = student["id"]

                return redirect(url_for("student_dashboard"))

            flash("Invalid student login details.", "error")

        elif role == "teacher":
            teacher = fetch_one(
                """
                SELECT *
                FROM teachers
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if teacher and check_password_hash(
                teacher["password_hash"],
                password
            ):
                session.clear()
                session["role"] = "teacher"
                session["user_id"] = teacher["id"]

                return redirect(url_for("teacher_dashboard"))

            flash("Invalid teacher login details.", "error")

        elif role == "admin":
            if (
                name.lower() == MASTER_ADMIN_NAME.lower()
                and password == MASTER_ADMIN_PASSWORD
            ):
                session.clear()
                session["role"] = "admin"
                session["admin_type"] = "master"
                session["user_id"] = "master"

                return redirect(url_for("admin_dashboard"))

            admin = fetch_one(
                """
                SELECT *
                FROM admins
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if admin and check_password_hash(
                admin["password_hash"],
                password
            ):
                session.clear()
                session["role"] = "admin"
                session["admin_type"] = "database"
                session["user_id"] = admin["id"]

                return redirect(url_for("admin_dashboard"))

            flash("Invalid administrator login details.", "error")

        else:
            flash("Please select a valid account type.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required("student")
def student_dashboard():
    student = current_user()

    if not student:
        session.clear()
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        student=student
    )


@app.route("/subjects")
@login_required()
def subjects():
    user = current_user()

    if not user:
        session.clear()
        return redirect(url_for("login"))

    if session.get("role") == "student":
        subject_rows = fetch_all(
            """
            SELECT *
            FROM subjects
            WHERE LOWER(class_name) = LOWER(%s)
            AND LOWER(department) = LOWER(%s)
            ORDER BY
                CASE term
                    WHEN 'First Term' THEN 1
                    WHEN 'Second Term' THEN 2
                    WHEN 'Third Term' THEN 3
                    ELSE 4
                END,
                name
            """,
            (
                user["class_name"],
                user["department"]
            )
        )

    else:
        subject_rows = fetch_all(
            """
            SELECT *
            FROM subjects
            ORDER BY
                class_name,
                department,
                CASE term
                    WHEN 'First Term' THEN 1
                    WHEN 'Second Term' THEN 2
                    WHEN 'Third Term' THEN 3
                    ELSE 4
                END,
                name
            """
        )

    grouped = {
        "First Term": [],
        "Second Term": [],
        "Third Term": []
    }

    for subject in subject_rows:
        if subject["term"] in grouped:
            grouped[subject["term"]].append(subject)

    return render_template(
        "subjects.html",
        subjects=grouped,
        user=user,
        role=session.get("role")
    )


@app.route("/results")
@login_required("student")
def results():
    student = current_user()

    if not student:
        session.clear()
        return redirect(url_for("login"))

    result_rows = fetch_all(
        """
        SELECT *
        FROM results
        WHERE student_id = %s
        ORDER BY
            CASE term
                WHEN 'First Term' THEN 1
                WHEN 'Second Term' THEN 2
                WHEN 'Third Term' THEN 3
                ELSE 4
            END,
            created_at DESC
        """,
        (student["id"],)
    )

    grouped = {
        "First Term": [],
        "Second Term": [],
        "Third Term": []
    }

    for result in result_rows:
        if result["term"] in grouped:
            grouped[result["term"]].append(result)

    return render_template(
        "results.html",
        results=grouped,
        student=student
    )


@app.route("/news")
@login_required()
def news():
    news_items = fetch_all(
        """
        SELECT *
        FROM news
        ORDER BY created_at DESC
        """
    )

    return render_template(
        "news.html",
        news_items=news_items
    )


@app.route("/teacher")
@login_required("teacher")
def teacher_dashboard():
    teacher = current_user()

    if not teacher:
        session.clear()
        return redirect(url_for("login"))

    return render_template(
        "teacher.html",
        teacher=teacher
    )


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    admin = current_user()

    if not admin:
        session.clear()
        return redirect(url_for("login"))

    return render_template(
        "admin_dashboard.html",
        admin=admin
    )


@app.route("/admin/students", methods=["GET", "POST"])
@login_required("admin")
def admin_students():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "register":
            name = normalize_name(request.form.get("name", ""))
            class_name = normalize_name(
                request.form.get("class_name", "")
            )
            department = normalize_department(
                request.form.get("department", "")
            )
            password = request.form.get("password", "")

            if not name or not class_name or not password:
                flash(
                    "Name, class and password are required.",
                    "error"
                )
                return redirect(url_for("admin_students"))

            existing = fetch_one(
                """
                SELECT id
                FROM students
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if existing:
                flash("A student with that name already exists.", "error")
                return redirect(url_for("admin_students"))

            execute(
                """
                INSERT INTO students
                (name, class_name, department, password_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    name,
                    class_name,
                    department,
                    generate_password_hash(password)
                )
            )

            flash("Student registered successfully.", "success")

        elif action == "edit":
            student_id = request.form.get("student_id")
            name = normalize_name(request.form.get("name", ""))
            class_name = normalize_name(
                request.form.get("class_name", "")
            )
            department = normalize_department(
                request.form.get("department", "")
            )
            password = request.form.get("password", "")

            if not student_id or not name or not class_name:
                flash(
                    "Student ID, name and class are required.",
                    "error"
                )
                return redirect(url_for("admin_students"))

            existing = fetch_one(
                """
                SELECT id
                FROM students
                WHERE LOWER(name) = LOWER(%s)
                AND id <> %s
                LIMIT 1
                """,
                (name, student_id)
            )

            if existing:
                flash(
                    "Another student already has that name.",
                    "error"
                )
                return redirect(url_for("admin_students"))

            if password:
                execute(
                    """
                    UPDATE students
                    SET name = %s,
                        class_name = %s,
                        department = %s,
                        password_hash = %s
                    WHERE id = %s
                    """,
                    (
                        name,
                        class_name,
                        department,
                        generate_password_hash(password),
                        student_id
                    )
                )
            else:
                execute(
                    """
                    UPDATE students
                    SET name = %s,
                        class_name = %s,
                        department = %s
                    WHERE id = %s
                    """,
                    (
                        name,
                        class_name,
                        department,
                        student_id
                    )
                )

            flash(
                "Student updated. Existing results remain attached to the student.",
                "success"
            )

        elif action == "delete":
            student_id = request.form.get("student_id")

            student = fetch_one(
                """
                SELECT id, name
                FROM students
                WHERE id = %s
                """,
                (student_id,)
            )

            if not student:
                flash("Student not found.", "error")
                return redirect(url_for("admin_students"))

            result_files = fetch_all(
                """
                SELECT storage_path
                FROM results
                WHERE student_id = %s
                """,
                (student_id,)
            )

            for result in result_files:
                storage_delete(result["storage_path"])

            execute(
                """
                DELETE FROM students
                WHERE id = %s
                """,
                (student_id,)
            )

            flash(
                f"Student '{student['name']}' and their results were deleted.",
                "success"
            )

    students = fetch_all(
        """
        SELECT id, name, class_name, department, created_at
        FROM students
        ORDER BY name
        """
    )

    return render_template(
        "admin_students.html",
        students=students
    )


@app.route("/admin/teachers", methods=["GET", "POST"])
@login_required("admin")
def admin_teachers():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "register":
            name = normalize_name(request.form.get("name", ""))
            password = request.form.get("password", "")

            if not name or not password:
                flash(
                    "Teacher name and password are required.",
                    "error"
                )
                return redirect(url_for("admin_teachers"))

            existing = fetch_one(
                """
                SELECT id
                FROM teachers
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if existing:
                flash(
                    "A teacher with that name already exists.",
                    "error"
                )
                return redirect(url_for("admin_teachers"))

            execute(
                """
                INSERT INTO teachers
                (name, password_hash)
                VALUES (%s, %s)
                """,
                (
                    name,
                    generate_password_hash(password)
                )
            )

            flash("Teacher registered successfully.", "success")

        elif action == "delete":
            teacher_id = request.form.get("teacher_id")

            execute(
                """
                DELETE FROM teachers
                WHERE id = %s
                """,
                (teacher_id,)
            )

            flash("Teacher deleted successfully.", "success")

    teachers = fetch_all(
        """
        SELECT id, name, created_at
        FROM teachers
        ORDER BY name
        """
    )

    return render_template(
        "admin_teachers.html",
        teachers=teachers
    )


@app.route("/admin/admins", methods=["GET", "POST"])
@login_required("admin")
def admin_admins():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name = normalize_name(request.form.get("name", ""))
            password = request.form.get("password", "")

            if not name or not password:
                flash(
                    "Administrator name and password are required.",
                    "error"
                )
                return redirect(url_for("admin_admins"))

            if name.lower() == MASTER_ADMIN_NAME.lower():
                flash(
                    "That name is reserved for the Master Administrator.",
                    "error"
                )
                return redirect(url_for("admin_admins"))

            existing = fetch_one(
                """
                SELECT id
                FROM admins
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if existing:
                flash(
                    "An administrator with that name already exists.",
                    "error"
                )
                return redirect(url_for("admin_admins"))

            execute(
                """
                INSERT INTO admins
                (name, password_hash)
                VALUES (%s, %s)
                """,
                (
                    name,
                    generate_password_hash(password)
                )
            )

            flash(
                f"Administrator '{name}' added successfully.",
                "success"
            )

        elif action == "delete":
            admin_id = request.form.get("admin_id")

            if (
                session.get("admin_type") == "database"
                and str(session.get("user_id")) == str(admin_id)
            ):
                flash(
                    "You cannot delete the administrator account you are currently using.",
                    "error"
                )
                return redirect(url_for("admin_admins"))

            execute(
                """
                DELETE FROM admins
                WHERE id = %s
                """,
                (admin_id,)
            )

            flash(
                "Administrator deleted successfully.",
                "success"
            )

    admins = fetch_all(
        """
        SELECT id, name, created_at
        FROM admins
        ORDER BY name
        """
    )

    return render_template(
        "admin_admins.html",
        admins=admins,
        master_admin_name=MASTER_ADMIN_NAME
    )


@app.route("/admin/subjects", methods=["GET", "POST"])
@login_required("admin")
def admin_subjects():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name = normalize_name(request.form.get("name", ""))
            class_name = normalize_name(
                request.form.get("class_name", "")
            )
            department = normalize_department(
                request.form.get("department", "")
            )
            term = normalize_term(
                request.form.get("term", "")
            )

            note = request.files.get("note")

            if not name or not class_name or not term:
                flash(
                    "Subject name, class and term are required.",
                    "error"
                )
                return redirect(url_for("admin_subjects"))

            note_path = None
            note_filename = None
            mime_type = None

            if note and note.filename:
                extension = get_file_extension(note.filename)

                if extension not in ALLOWED_NOTE_EXTENSIONS:
                    flash(
                        "That file type is not allowed.",
                        "error"
                    )
                    return redirect(url_for("admin_subjects"))

                original_name = secure_filename(note.filename)

                if not original_name:
                    flash(
                        "Invalid file name.",
                        "error"
                    )
                    return redirect(url_for("admin_subjects"))

                note_bytes = note.read()
                mime_type = note.mimetype or mimetypes.guess_type(
                    original_name
                )[0] or "application/octet-stream"

                safe_class = secure_filename(
                    class_name.replace(" ", "_")
                )

                safe_department = secure_filename(
                    department.replace(" ", "_")
                )

                storage_name = (
                    f"notes/{safe_class}/"
                    f"{safe_department}/"
                    f"{term.replace(' ', '_')}/"
                    f"{original_name}"
                )

                if not storage_upload(
                    storage_name,
                    note_bytes,
                    mime_type
                ):
                    flash(
                        "The note could not be uploaded.",
                        "error"
                    )
                    return redirect(url_for("admin_subjects"))

                note_path = storage_name
                note_filename = original_name

            execute(
                """
                INSERT INTO subjects
                (
                    name,
                    class_name,
                    department,
                    term,
                    note_path,
                    note_filename,
                    mime_type
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    name,
                    class_name,
                    department,
                    term,
                    note_path,
                    note_filename,
                    mime_type
                )
            )

            flash(
                "Subject/e-note added successfully.",
                "success"
            )

        elif action == "delete":
            subject_id = request.form.get("subject_id")

            subject = fetch_one(
                """
                SELECT note_path
                FROM subjects
                WHERE id = %s
                """,
                (subject_id,)
            )

            if subject:
                storage_delete(subject["note_path"])

            execute(
                """
                DELETE FROM subjects
                WHERE id = %s
                """,
                (subject_id,)
            )

            flash(
                "Subject deleted successfully.",
                "success"
            )

    subjects_rows = fetch_all(
        """
        SELECT *
        FROM subjects
        ORDER BY
            class_name,
            department,
            CASE term
                WHEN 'First Term' THEN 1
                WHEN 'Second Term' THEN 2
                WHEN 'Third Term' THEN 3
                ELSE 4
            END,
            name
        """
    )

    return render_template(
        "admin_subjects.html",
        subjects=subjects_rows
    )


@app.route("/admin/results", methods=["GET", "POST"])
@login_required("admin")
def admin_results():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "upload":
            student_id = request.form.get("student_id")
            term = normalize_term(
                request.form.get("term", "")
            )
            result_file = request.files.get("result_file")

            student = fetch_one(
                """
                SELECT id, name, class_name, department
                FROM students
                WHERE id = %s
                """,
                (student_id,)
            )

            if not student:
                flash(
                    "Student not found.",
                    "error"
                )
                return redirect(url_for("admin_results"))

            if not term:
                flash(
                    "Please select a valid term.",
                    "error"
                )
                return redirect(url_for("admin_results"))

            if not result_file or not result_file.filename:
                flash(
                    "Please select a result file.",
                    "error"
                )
                return redirect(url_for("admin_results"))

            extension = get_file_extension(
                result_file.filename
            )

            if extension not in ALLOWED_RESULT_EXTENSIONS:
                flash(
                    "Allowed result files are PDF, ODS, XLSX, XLS and CSV.",
                    "error"
                )
                return redirect(url_for("admin_results"))

            filename = secure_filename(
                result_file.filename
            )

            if not filename:
                flash(
                    "Invalid result file name.",
                    "error"
                )
                return redirect(url_for("admin_results"))

            file_bytes = result_file.read()

            mime_type = (
                result_file.mimetype
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )

            safe_student = secure_filename(
                student["name"].replace(" ", "_")
            )

            storage_path = (
                f"results/{student['id']}/"
                f"{term.replace(' ', '_')}/"
                f"{filename}"
            )

            if not storage_upload(
                storage_path,
                file_bytes,
                mime_type
            ):
                flash(
                    "Result upload failed.",
                    "error"
                )
                return redirect(url_for("admin_results"))

            execute(
                """
                INSERT INTO results
                (
                    student_id,
                    term,
                    filename,
                    storage_path,
                    mime_type
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    student["id"],
                    term,
                    filename,
                    storage_path,
                    mime_type
                )
            )

            flash(
                f"Result uploaded for {student['name']}.",
                "success"
            )

        elif action == "delete":
            result_id = request.form.get("result_id")

            result = fetch_one(
                """
                SELECT storage_path
                FROM results
                WHERE id = %s
                """,
                (result_id,)
            )

            if result:
                storage_delete(
                    result["storage_path"]
                )

            execute(
                """
                DELETE FROM results
                WHERE id = %s
                """,
                (result_id,)
            )

            flash(
                "Result deleted successfully.",
                "success"
            )

    students = fetch_all(
        """
        SELECT id, name, class_name, department
        FROM students
        ORDER BY name
        """
    )

    results_rows = fetch_all(
        """
        SELECT
            results.id,
            results.term,
            results.filename,
            results.created_at,
            students.name AS student_name,
            students.class_name,
            students.department
        FROM results
        JOIN students
            ON students.id = results.student_id
        ORDER BY
            students.name,
            CASE results.term
                WHEN 'First Term' THEN 1
                WHEN 'Second Term' THEN 2
                WHEN 'Third Term' THEN 3
                ELSE 4
            END,
            results.created_at DESC
        """
    )

    return render_template(
        "admin_results.html",
        students=students,
        results=results_rows
    )


@app.route("/admin/news", methods=["GET", "POST"])
@login_required("admin")
def admin_news():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            title = request.form.get(
                "title",
                ""
            ).strip()

            body = request.form.get(
                "body",
                ""
            ).strip()

            if not title or not body:
                flash(
                    "News title and message are required.",
                    "error"
                )
                return redirect(url_for("admin_news"))

            execute(
                """
                INSERT INTO news
                (title, body)
                VALUES (%s, %s)
                """,
                (title, body)
            )

            flash(
                "School news published successfully.",
                "success"
            )

        elif action == "delete":
            news_id = request.form.get("news_id")

            execute(
                """
                DELETE FROM news
                WHERE id = %s
                """,
                (news_id,)
            )

            flash(
                "News deleted successfully.",
                "success"
            )

    news_items = fetch_all(
        """
        SELECT *
        FROM news
        ORDER BY created_at DESC
        """
    )

    return render_template(
        "admin_news.html",
        news_items=news_items
    )


@app.route("/file/<kind>/<int:file_id>")
@login_required()
def view_file(kind, file_id):
    if kind == "result":
        result = fetch_one(
            """
            SELECT
                results.*,
                students.name AS student_name,
                students.class_name,
                students.department
            FROM results
            JOIN students
                ON students.id = results.student_id
            WHERE results.id = %s
            """,
            (file_id,)
        )

        if not result:
            abort(404)

        if session.get("role") == "student":
            user = current_user()

            if not user or int(user["id"]) != int(result["student_id"]):
                abort(403)

        signed_url = get_signed_url(
            result["storage_path"]
        )

        if not signed_url:
            abort(500)

        extension = get_file_extension(
            result["filename"]
        )

        spreadsheet_html = None

        if extension in {
            ".csv",
            ".ods",
            ".xlsx",
            ".xls",
            ".xlsm"
        }:
            try:
                response = supabase.storage.from_(
                    SUPABASE_BUCKET
                ).download(
                    result["storage_path"]
                )

                spreadsheet_html = render_spreadsheet(
                    response,
                    result["filename"]
                )

            except Exception as e:
                print("Spreadsheet preview error:", e)

        return render_template(
            "view_result.html",
            result=result,
            signed_url=signed_url,
            spreadsheet_html=spreadsheet_html,
            extension=extension
        )

    elif kind == "note":
        subject = fetch_one(
            """
            SELECT *
            FROM subjects
            WHERE id = %s
            """,
            (file_id,)
        )

        if not subject:
            abort(404)

        if not subject["note_path"]:
            abort(404)

        if session.get("role") == "student":
            student = current_user()

            if not student:
                abort(403)

            if (
                student["class_name"].lower()
                != subject["class_name"].lower()
            ):
                abort(403)

            if (
                student["department"].lower()
                != subject["department"].lower()
            ):
                abort(403)

        signed_url = get_signed_url(
            subject["note_path"]
        )

        if not signed_url:
            abort(500)

        return render_template(
            "view_result.html",
            result={
                "filename": subject["note_filename"] or subject["name"],
                "term": subject["term"],
                "student_name": subject["name"]
            },
            signed_url=signed_url,
            spreadsheet_html=None,
            extension=get_file_extension(
                subject["note_filename"] or ""
            )
        )

    abort(404)


@app.route("/download/<kind>/<int:file_id>")
@login_required()
def download_file(kind, file_id):
    if kind == "result":
        result = fetch_one(
            """
            SELECT *
            FROM results
            WHERE id = %s
            """,
            (file_id,)
        )

        if not result:
            abort(404)

        if session.get("role") == "student":
            user = current_user()

            if not user or int(user["id"]) != int(result["student_id"]):
                abort(403)

        try:
            file_bytes = supabase.storage.from_(
                SUPABASE_BUCKET
            ).download(
                result["storage_path"]
            )

            return send_file(
                io.BytesIO(file_bytes),
                as_attachment=True,
                download_name=result["filename"],
                mimetype=result["mime_type"]
                or "application/octet-stream"
            )

        except Exception as e:
            print("Result download error:", e)
            abort(500)

    if kind == "note":
        subject = fetch_one(
            """
            SELECT *
            FROM subjects
            WHERE id = %s
            """,
            (file_id,)
        )

        if not subject or not subject["note_path"]:
            abort(404)

        if session.get("role") == "student":
            student = current_user()

            if not student:
                abort(403)

            if (
                student["class_name"].lower()
                != subject["class_name"].lower()
                or
                student["department"].lower()
                != subject["department"].lower()
            ):
                abort(403)

        try:
            file_bytes = supabase.storage.from_(
                SUPABASE_BUCKET
            ).download(
                subject["note_path"]
            )

            filename = subject["note_filename"] or subject["name"]

            return send_file(
                io.BytesIO(file_bytes),
                as_attachment=True,
                download_name=filename,
                mimetype=subject["mime_type"]
                or "application/octet-stream"
            )

        except Exception as e:
            print("Note download error:", e)
            abort(500)

    abort(404)


@app.context_processor
def inject_user():
    return {
        "logged_user": current_user()
    }


try:
    initialize_database()
except Exception as e:
    print("Database initialization error:", e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
