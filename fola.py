```python
import os
import io
import mimetypes
import tempfile
import subprocess
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    send_file,
    flash
)

from werkzeug.utils import secure_filename

from supabase import create_client


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-in-render"
)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

DATABASE_URL = os.environ.get("DATABASE_URL")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SUPABASE_BUCKET = "school files"


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set.")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not set.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is not set.")


# =========================================================
# SUPABASE
# =========================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# =========================================================
# TEMPORARY FILE FOLDER
# =========================================================

TEMP_FOLDER = os.path.join(
    tempfile.gettempdir(),
    "school_portal"
)

os.makedirs(TEMP_FOLDER, exist_ok=True)


# =========================================================
# ALLOWED RESULT FILES
# =========================================================

ALLOWED_RESULT_EXTENSIONS = {
    "pdf",
    "xlsx",
    "xls",
    "ods",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp"
}


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


# =========================================================
# CREATE DATABASE TABLES
# =========================================================

def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            class_name TEXT NOT NULL,
            department TEXT NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id SERIAL PRIMARY KEY,
            subject_name TEXT NOT NULL,
            subject_link TEXT NOT NULL,
            class_name TEXT NOT NULL,
            department TEXT NOT NULL,
            term TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL,
            student_name TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            term TEXT NOT NULL,
            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            date TEXT NOT NULL,
            admin TEXT NOT NULL
        )
    """)

    conn.commit()

    cur.close()
    conn.close()


init_db()


# =========================================================
# ADMIN ACCOUNTS
# =========================================================

try:
    from data import ADMINS
except Exception:
    ADMINS = {
        "Admin": "admin2026"
    }


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def allowed_result_file(filename):

    if not filename:
        return False

    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_RESULT_EXTENSIONS


def is_senior_class(class_name):

    if not class_name:
        return False

    value = class_name.strip().upper()

    return value.startswith("SS")


def get_student_by_name(name):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM students
        WHERE LOWER(name) = LOWER(%s)
        """,
        (name.strip(),)
    )

    student = cur.fetchone()

    cur.close()
    conn.close()

    return student


# =========================================================
# LOGIN DECORATORS
# =========================================================

def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))

        return function(*args, **kwargs)

    return wrapper


def student_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("student_logged_in"):
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


def teacher_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not session.get("teacher_logged_in"):
            return redirect(url_for("teacher_login"))

        return function(*args, **kwargs)

    return wrapper


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return redirect(url_for("login"))


# =========================================================
# STUDENT LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        password = request.form.get("password", "").strip()
        class_name = request.form.get("class_name", "").strip()
        department = request.form.get("department", "").strip()

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM students
            WHERE LOWER(name) = LOWER(%s)
            AND LOWER(class_name) = LOWER(%s)
            AND LOWER(department) = LOWER(%s)
            """,
            (
                name,
                class_name,
                department
            )
        )

        student = cur.fetchone()

        cur.close()
        conn.close()

        if student and password == student["password"]:

            session.clear()

            session["student_logged_in"] = True
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]
            session["class_name"] = student["class_name"]
            session["department"] = student["department"]

            return redirect(url_for("dashboard"))

        flash("Invalid student details.")

    return render_template("login.html")


# =========================================================
# STUDENT DASHBOARD
# =========================================================

@app.route("/dashboard")
@student_required
def dashboard():

    return render_template(
        "dashboard.html",
        student_name=session.get("student_name"),
        class_name=session.get("class_name"),
        department=session.get("department")
    )


# =========================================================
# STUDENT LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================================================
# STUDENT SUBJECTS
# =========================================================

@app.route("/subjects")
@student_required
def subjects():

    class_name = session.get("class_name")
    department = session.get("department")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM subjects
        WHERE LOWER(class_name) = LOWER(%s)
        AND LOWER(department) = LOWER(%s)
        ORDER BY subject_name
        """,
        (
            class_name,
            department
        )
    )

    subjects_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "subjects.html",
        subjects=subjects_list
    )


# =========================================================
# STUDENT RESULTS
# =========================================================

@app.route("/results")
@student_required
def results():

    student_id = session.get("student_id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM results
        WHERE student_id = %s
        ORDER BY id DESC
        """,
        (student_id,)
    )

    results_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "results.html",
        results=results_list
    )


# =========================================================
# VIEW STUDENT RESULT
# =========================================================

@app.route("/result_file/<int:result_id>")
@student_required
def result_file(result_id):

    student_id = session.get("student_id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM results
        WHERE id = %s
        AND student_id = %s
        """,
        (
            result_id,
            student_id
        )
    )

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result:
        return "Result not found.", 404

    storage_path = "results/" + result["filename"]

    try:

        file_data = supabase.storage.from_(
            SUPABASE_BUCKET
        ).download(storage_path)

    except Exception as e:

        print("SUPABASE DOWNLOAD ERROR:", e)

        return "The result file could not be opened.", 500

    mime_type = mimetypes.guess_type(
        result["original_filename"]
    )[0]

    if not mime_type:
        mime_type = "application/pdf"

    return send_file(
        io.BytesIO(file_data),
        mimetype=mime_type,
        download_name=result["original_filename"],
        as_attachment=False
    )


# =========================================================
# NEWS
# =========================================================

@app.route("/news")
@student_required
def news():

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM news
        ORDER BY id DESC
        """
    )

    news_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "news.html",
        news=news_list
    )


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.route("/admin", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        password = request.form.get("password", "").strip()

        for admin_name, admin_password in ADMINS.items():

            if name.lower() == admin_name.lower():

                if password == admin_password:

                    session.clear()

                    session["admin_logged_in"] = True
                    session["admin_name"] = admin_name

                    return redirect(
                        url_for("admin_dashboard")
                    )

        flash("Invalid admin username or password.")

    return render_template("admin.html")


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin_dashboard")
@admin_required
def admin_dashboard():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM students
        ORDER BY name
    """)

    students = cur.fetchall()

    cur.execute("""
        SELECT *
        FROM teachers
        ORDER BY name
    """)

    teachers = cur.fetchall()

    cur.execute("""
        SELECT *
        FROM subjects
        ORDER BY class_name, subject_name
    """)

    subjects_list = cur.fetchall()

    cur.execute("""
        SELECT *
        FROM news
        ORDER BY id DESC
    """)

    news_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "admin_dashboard.html",
        students=students,
        teachers=teachers,
        subjects=subjects_list,
        news=news_list
    )


# =========================================================
# REGISTER STUDENT
# =========================================================

@app.route("/add_student", methods=["POST"])
@admin_required
def add_student():

    name = request.form.get("name", "").strip()
    class_name = request.form.get("class_name", "").strip()
    department = request.form.get("department", "").strip()
    password = request.form.get("password", "").strip()

    if not name or not class_name or not password:
        flash("Please fill all required student fields.")
        return redirect(url_for("admin_dashboard"))

    if is_senior_class(class_name):

        if department.lower() not in [
            "science",
            "art",
            "commercial"
        ]:
            flash(
                "Senior students must have Science, Art or Commercial department."
            )

            return redirect(
                url_for("admin_dashboard")
            )

    else:

        department = "General"

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO students
            (name, class_name, department, password)
            VALUES (%s, %s, %s, %s)
            """,
            (
                name,
                class_name,
                department,
                password
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        flash("Student registered successfully.")

    except Exception as e:

        print("ADD STUDENT ERROR:", e)

        flash(
            "Could not register student. The name may already exist."
        )

    return redirect(url_for("admin_dashboard"))


# =========================================================
# DELETE STUDENT
# =========================================================

@app.route("/delete_student/<int:student_id>")
@admin_required
def delete_student(student_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM students
        WHERE id = %s
        """,
        (student_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("Student deleted.")

    return redirect(url_for("admin_dashboard"))


# =========================================================
# ADD TEACHER
# =========================================================

@app.route("/add_teacher", methods=["POST"])
@admin_required
def add_teacher():

    name = request.form.get("name", "").strip()
    password = request.form.get("password", "").strip()

    if not name or not password:

        flash("Enter teacher name and password.")

        return redirect(
            url_for("admin_dashboard")
        )

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO teachers
            (name, password)
            VALUES (%s, %s)
            """,
            (
                name,
                password
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        flash("Teacher added successfully.")

    except Exception as e:

        print("ADD TEACHER ERROR:", e)

        flash(
            "Could not add teacher. The name may already exist."
        )

    return redirect(url_for("admin_dashboard"))


# =========================================================
# DELETE TEACHER
# =========================================================

@app.route("/delete_teacher/<int:teacher_id>")
@admin_required
def delete_teacher(teacher_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM teachers
        WHERE id = %s
        """,
        (teacher_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("Teacher deleted.")

    return redirect(url_for("admin_dashboard"))


# =========================================================
# ADD SUBJECT
# =========================================================

@app.route("/add_subject", methods=["POST"])
@admin_required
def add_subject():

    subject_name = request.form.get(
        "subject_name",
        ""
    ).strip()

    subject_link = request.form.get(
        "subject_link",
        ""
    ).strip()

    class_name = request.form.get(
        "class_name",
        ""
    ).strip()

    department = request.form.get(
        "department",
        ""
    ).strip()

    term = request.form.get(
        "term",
        ""
    ).strip()

    if not all([
        subject_name,
        subject_link,
        class_name,
        department,
        term
    ]):

        flash("Please fill all subject fields.")

        return redirect(
            url_for("admin_dashboard")
        )

    if not is_senior_class(class_name):

        department = "General"

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO subjects
            (
                subject_name,
                subject_link,
                class_name,
                department,
                term
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                subject_name,
                subject_link,
                class_name,
                department,
                term
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        flash("Subject added successfully.")

    except Exception as e:

        print("ADD SUBJECT ERROR:", e)

        flash("Could not add subject.")

    return redirect(url_for("admin_dashboard"))


# =========================================================
# DELETE SUBJECT
# =========================================================

@app.route("/delete_subject/<int:subject_id>")
@admin_required
def delete_subject(subject_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM subjects
        WHERE id = %s
        """,
        (subject_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("Subject deleted.")

    return redirect(url_for("admin_dashboard"))


# =========================================================
# ADD NEWS
# =========================================================

@app.route("/add_news", methods=["POST"])
@admin_required
def add_news():

    title = request.form.get(
        "title",
        ""
    ).strip()

    content = request.form.get(
        "content",
        ""
    ).strip()

    if not title or not content:

        flash("Please enter the news title and content.")

        return redirect(
            url_for("admin_dashboard")
        )

    from datetime import datetime

    date = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    admin_name = session.get(
        "admin_name",
        "Admin"
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO news
        (title, content, date, admin)
        VALUES (%s, %s, %s, %s)
        """,
        (
            title,
            content,
            date,
            admin_name
        )
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("News uploaded successfully.")

    return redirect(
        url_for("admin_dashboard")
    )


# =========================================================
# DELETE NEWS
# =========================================================

@app.route("/delete_news/<int:news_id>")
@admin_required
def delete_news(news_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM news
        WHERE id = %s
        """,
        (news_id,)
    )

    conn.commit()

    cur.close()
    conn.close()

    flash("News deleted.")

    return redirect(
        url_for("admin_dashboard")
    )


# =========================================================
# CONVERT EXCEL / ODS TO PDF
# =========================================================

def convert_spreadsheet_to_pdf(input_path):

    """
    Converts:
        .xlsx
        .xls
        .ods

    to PDF using LibreOffice.

    LibreOffice is installed in the Docker image.
    """

    output_directory = TEMP_FOLDER

    base_name = os.path.splitext(
        os.path.basename(input_path)
    )[0]

    expected_pdf = os.path.join(
        output_directory,
        base_name + ".pdf"
    )

    # Remove old PDF if it exists.
    if os.path.exists(expected_pdf):

        try:
            os.remove(expected_pdf)
        except Exception:
            pass

    try:

        command = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            output_directory,
            input_path
        ]

        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180
        )

        print(
            "LIBREOFFICE STDOUT:",
            process.stdout
        )

        print(
            "LIBREOFFICE STDERR:",
            process.stderr
        )

        if process.returncode != 0:

            print(
                "LibreOffice returned:",
                process.returncode
            )

            return None

        if not os.path.exists(expected_pdf):

            print(
                "PDF was not created:",
                expected_pdf
            )

            return None

        return expected_pdf

    except subprocess.TimeoutExpired:

        print("LibreOffice conversion timed out.")

        return None

    except Exception as e:

        print(
            "LIBREOFFICE ERROR:",
            repr(e)
        )

        return None


# =========================================================
# UPLOAD STUDENT RESULT
# =========================================================

@app.route(
    "/upload_result",
    methods=["POST"]
)
@admin_required
def upload_result():

    student_id = request.form.get(
        "student_id"
    )

    term = request.form.get(
        "term",
        ""
    ).strip()

    uploaded_file = request.files.get(
        "result_file"
    )

    if not student_id:

        flash("Please select a student.")

        return redirect(
            url_for("admin_dashboard")
        )

    if not term:

        flash("Please select the result term.")

        return redirect(
            url_for("admin_dashboard")
        )

    if not uploaded_file or not uploaded_file.filename:

        flash("Please select a result file.")

        return redirect(
            url_for("admin_dashboard")
        )

    original_filename = uploaded_file.filename

    if not allowed_result_file(
        original_filename
    ):

        flash(
            "Invalid file type. Use PDF, Excel, ODS or an image."
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # -----------------------------------------------------
    # GET STUDENT
    # -----------------------------------------------------

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM students
        WHERE id = %s
        """,
        (student_id,)
    )

    student = cur.fetchone()

    cur.close()
    conn.close()

    if not student:

        flash("Student not found.")

        return redirect(
            url_for("admin_dashboard")
        )

    # -----------------------------------------------------
    # SAVE ORIGINAL FILE TEMPORARILY
    # -----------------------------------------------------

    safe_original_name = secure_filename(
        original_filename
    )

    if not safe_original_name:

        flash("Invalid filename.")

        return redirect(
            url_for("admin_dashboard")
        )

    input_path = os.path.join(
        TEMP_FOLDER,
        safe_original_name
    )

    try:

        uploaded_file.save(input_path)

    except Exception as e:

        print(
            "TEMP SAVE ERROR:",
            repr(e)
        )

        flash(
            "The uploaded file could not be saved."
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # -----------------------------------------------------
    # DETERMINE EXTENSION
    # -----------------------------------------------------

    extension = os.path.splitext(
        safe_original_name
    )[1].lower()

    final_path = input_path

    # -----------------------------------------------------
    # CONVERT SPREADSHEET TO PDF
    # -----------------------------------------------------

    if extension in [
        ".xlsx",
        ".xls",
        ".ods"
    ]:

        final_path = convert_spreadsheet_to_pdf(
            input_path
        )

        if not final_path:

            # Print useful diagnostic information
            print(
                "FAILED TO CONVERT:",
                input_path
            )

            try:
                os.remove(input_path)
            except Exception:
                pass

            flash(
                "The spreadsheet could not be converted to PDF. "
                "Please check the Render logs."
            )

            return redirect(
                url_for("admin_dashboard")
            )

    # -----------------------------------------------------
    # FINAL FILE NAME
    # -----------------------------------------------------

    final_extension = os.path.splitext(
        final_path
    )[1].lower()

    if final_extension == ".pdf":

        storage_filename = (
            f"student_{student['id']}_"
            f"{term.lower().replace(' ', '_')}_"
            f"{os.urandom(8).hex()}.pdf"
        )

    else:

        storage_filename = (
            f"student_{student['id']}_"
            f"{term.lower().replace(' ', '_')}_"
            f"{os.urandom(8).hex()}"
            f"{final_extension}"
        )

    storage_path = (
        "results/" + storage_filename
    )

    # -----------------------------------------------------
    # DETERMINE MIME TYPE
    # -----------------------------------------------------

    mime_type = mimetypes.guess_type(
        final_path
    )[0]

    if not mime_type:

        mime_type = "application/pdf"

    # -----------------------------------------------------
    # READ FILE
    # -----------------------------------------------------

    try:

        with open(
            final_path,
            "rb"
        ) as file:

            file_data = file.read()

    except Exception as e:

        print(
            "READ FILE ERROR:",
            repr(e)
        )

        flash(
            "The result file could not be read."
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # -----------------------------------------------------
    # UPLOAD TO SUPABASE
    # -----------------------------------------------------

    try:

        supabase.storage.from_(
            SUPABASE_BUCKET
        ).upload(
            path=storage_path,
            file=file_data,
            file_options={
                "content-type": mime_type,
                "cache-control": "3600",
                "upsert": "true"
            }
        )

    except Exception as e:

        print(
            "SUPABASE UPLOAD ERROR:",
            repr(e)
        )

        flash(
            "The result could not be uploaded to storage."
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # -----------------------------------------------------
    # SAVE RESULT RECORD IN POSTGRESQL
    # -----------------------------------------------------

    try:

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO results
            (
                student_id,
                student_name,
                filename,
                original_filename,
                term
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                student["id"],
                student["name"],
                storage_filename,
                original_filename,
                term
            )
        )

        conn.commit()

        cur.close()
        conn.close()

    except Exception as e:

        print(
            "DATABASE RESULT ERROR:",
            repr(e)
        )

        # Try to remove uploaded file if DB insertion fails.
        try:

            supabase.storage.from_(
                SUPABASE_BUCKET
            ).remove([
                storage_path
            ])

        except Exception:
            pass

        flash(
            "The result was uploaded but could not be registered."
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # -----------------------------------------------------
    # CLEAN TEMP FILES
    # -----------------------------------------------------

    try:

        if os.path.exists(input_path):
            os.remove(input_path)

    except Exception:
        pass

    if final_path != input_path:

        try:

            if os.path.exists(final_path):
                os.remove(final_path)

        except Exception:
            pass

    flash(
        f"Result uploaded successfully for {student['name']}."
    )

    return redirect(
        url_for("admin_dashboard")
    )


# =========================================================
# TEACHER LOGIN
# =========================================================

@app.route(
    "/teacher_login",
    methods=["GET", "POST"]
)
def teacher_login():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        ).strip()

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM teachers
            WHERE LOWER(name) = LOWER(%s)
            """,
            (name,)
        )

        teacher = cur.fetchone()

        cur.close()
        conn.close()

        if teacher and password == teacher["password"]:

            session.clear()

            session["teacher_logged_in"] = True
            session["teacher_name"] = teacher["name"]

            return redirect(
                url_for("teacher_dashboard")
            )

        flash(
            "Invalid teacher username or password."
        )

    return render_template(
        "teacher_login.html"
    )


# =========================================================
# TEACHER DASHBOARD
# =========================================================

@app.route("/teacher_dashboard")
@teacher_required
def teacher_dashboard():

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM subjects
        ORDER BY class_name, department, term, subject_name
        """
    )

    subjects_list = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "teacher_dashboard.html",
        subjects=subjects_list,
        teacher_name=session.get("teacher_name")
    )


# =========================================================
# TEACHER LOGOUT
# =========================================================

@app.route("/teacher_logout")
def teacher_logout():

    session.clear()

    return redirect(
        url_for("teacher_login")
    )


# =========================================================
# RUN APP
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
```

