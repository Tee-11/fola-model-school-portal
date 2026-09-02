import os
import io
import tempfile
import uuid
import zipfile
from functools import wraps
from datetime import datetime
from mimetypes import guess_type

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, send_file
)
from supabase import create_client
from openpyxl import load_workbook
from odf.opendocument import load as load_ods_document
from odf.table import Table as ODFTable, TableRow as ODFTableRow, TableCell as ODFTableCell
from odf.text import P as ODFParagraph

try:
    from data import ADMINS
except ImportError:
    ADMINS = {}

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-in-render"
)

DATABASE_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_BUCKET = "school files"

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing.")
if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing.")
if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# =========================
# DATABASE
# =========================

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )


def init_db():
    conn = get_db()
    try:
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
    finally:
        conn.close()


init_db()


# =========================
# HELPERS
# =========================

ALLOWED_RESULT_EXTENSIONS = {
    "pdf", "xlsx", "xlsm", "xls", "ods",
    "png", "jpg", "jpeg", "gif", "webp"
}


def normalize_name(name):
    return " ".join((name or "").strip().split())


def get_extension(filename):
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def is_jss(class_name):
    return (class_name or "").upper().startswith("JSS")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin" not in session:
            flash("Please log in as administrator.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "student_id" not in session:
            flash("Please log in as a student.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def teacher_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "teacher_id" not in session:
            flash("Please log in as a teacher.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def clear_login_sessions():
    session.pop("admin", None)
    session.pop("student_id", None)
    session.pop("student_name", None)
    session.pop("teacher_id", None)
    session.pop("teacher_name", None)


def find_admin(name, password):
    """
    Reads the admin account from data.py.

    Example data.py:

        ADMINS = {
            "Admin": "admin2026"
        }

    You can add more admins to that dictionary.
    """
    typed_name = normalize_name(name).lower()

    if not isinstance(ADMINS, dict):
        return None

    for admin_name, admin_password in ADMINS.items():
        if (
            normalize_name(str(admin_name)).lower() == typed_name
            and str(admin_password) == password
        ):
            return str(admin_name)

    return None


def storage_path(filename):
    return f"results/{filename}"


def upload_to_storage(file_bytes, path, content_type):
    return supabase.storage.from_(SUPABASE_BUCKET).upload(
        path=path,
        file=file_bytes,
        file_options={
            "content-type": content_type,
            "cache-control": "3600",
            "upsert": "true"
        }
    )


def download_from_storage(path):
    return supabase.storage.from_(SUPABASE_BUCKET).download(path)


def delete_from_storage(path):
    try:
        supabase.storage.from_(SUPABASE_BUCKET).remove([path])
    except Exception as e:
        print("Storage delete warning:", repr(e))


def read_excel(file_bytes, extension):
    """Read XLSX/XLSM directly from bytes."""
    if extension not in {"xlsx", "xlsm"}:
        raise ValueError("Unsupported modern Excel extension.")

    workbook = load_workbook(
        io.BytesIO(file_bytes),
        read_only=True,
        data_only=False
    )

    sheets = {}

    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append([
                "" if value is None else value
                for value in row
            ])
        sheets[sheet_name] = rows

    workbook.close()
    return sheets


def _ods_cell_text(cell):
    """Return visible text and ODS repeat/span information for one cell."""
    parts = []
    for paragraph in cell.getElementsByType(ODFParagraph):
        text_parts = []
        for node in paragraph.childNodes:
            data = getattr(node, "data", None)
            if data is not None:
                text_parts.append(str(data))
        text = "".join(text_parts).strip()
        if text:
            parts.append(text)

    value = " ".join(parts).strip()

    repeat = cell.getAttribute("numbercolumnsrepeated")
    try:
        repeat = int(repeat) if repeat else 1
    except (TypeError, ValueError):
        repeat = 1

    span = cell.getAttribute("numbercolumnsspanned")
    try:
        span = int(span) if span else 1
    except (TypeError, ValueError):
        span = 1

    return value, max(1, repeat), max(1, span)


def read_ods(file_bytes):
    """
    Read an ODS spreadsheet and return a dictionary of HTML-table-ready rows.

    Empty trailing rows and columns are removed. This is important because
    spreadsheet programs often store a large formatted area even when the
    report card only contains a small amount of actual data.
    """
    if not file_bytes:
        raise ValueError("Empty ODS file.")

    temp_path = os.path.join(
        os.getenv("TMPDIR") or tempfile.gettempdir(),
        f"fola_result_{uuid.uuid4().hex}.ods"
    )

    document = None

    try:
        with open(temp_path, "wb") as output:
            output.write(file_bytes)

        document = load_ods_document(temp_path)
        sheets = {}

        for table in document.spreadsheet.getElementsByType(ODFTable):
            sheet_name = str(table.getAttribute("name") or "Sheet")
            rows = []

            for row in table.childNodes:
                if not hasattr(row, "qname") or row.qname != ODFTableRow.qname:
                    continue

                values = []

                for cell in row.childNodes:
                    if not hasattr(cell, "qname") or cell.qname != ODFTableCell.qname:
                        continue

                    value, repeat, span = _ods_cell_text(cell)

                    # Preserve repeated/spanned columns so report-card
                    # information does not disappear.
                    values.extend([value] * max(1, repeat * span))

                rows.append(values)

            # Remove empty trailing cells and completely empty trailing rows.
            cleaned_rows = []
            max_columns = 0

            for row in rows:
                cleaned = list(row)

                while cleaned and str(cleaned[-1]).strip() == "":
                    cleaned.pop()

                if cleaned:
                    cleaned_rows.append(cleaned)
                    max_columns = max(max_columns, len(cleaned))

            # Give all rows the same number of columns.
            for row in cleaned_rows:
                row.extend([""] * (max_columns - len(row)))

            sheets[sheet_name] = cleaned_rows

        if not sheets:
            raise ValueError("No sheets found in ODS file.")

        return sheets

    finally:
        document = None
        try:
            os.remove(temp_path)
        except OSError:
            pass


# =========================
# LOGIN
# =========================

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        user_type = request.form.get(
            "user_type", ""
        ).strip().lower()

        name = normalize_name(
            request.form.get("name", "")
        )

        password = request.form.get(
            "password", ""
        )

        if not name or not password:
            flash("Please enter your name and password.")
            return render_template("login.html")

        # ADMIN
        if user_type == "admin":

            admin_name = find_admin(
                name,
                password
            )

            if admin_name:
                clear_login_sessions()
                session["admin"] = admin_name
                return redirect(
                    url_for("admin_dashboard")
                )

            flash("Invalid administrator name or password.")
            return render_template("login.html")

        # STUDENT
        if user_type == "student":

            conn = get_db()
            try:
                cur = conn.cursor(
                    cursor_factory=RealDictCursor
                )

                cur.execute("""
                    SELECT *
                    FROM students
                    WHERE LOWER(TRIM(name))
                          = LOWER(TRIM(%s))
                    LIMIT 1
                """, (name,))

                student = cur.fetchone()
            finally:
                conn.close()

            if (
                student
                and str(student["password"]) == password
            ):
                clear_login_sessions()

                session["student_id"] = student["id"]
                session["student_name"] = student["name"]

                return redirect(
                    url_for("dashboard")
                )

            flash("Invalid student details.")
            return render_template("login.html")

        # TEACHER
        if user_type == "teacher":

            conn = get_db()
            try:
                cur = conn.cursor(
                    cursor_factory=RealDictCursor
                )

                cur.execute("""
                    SELECT *
                    FROM teachers
                    WHERE LOWER(TRIM(name))
                          = LOWER(TRIM(%s))
                    LIMIT 1
                """, (name,))

                teacher = cur.fetchone()
            finally:
                conn.close()

            if (
                teacher
                and str(teacher["password"]) == password
            ):
                clear_login_sessions()

                session["teacher_id"] = teacher["id"]
                session["teacher_name"] = teacher["name"]

                return redirect(
                    url_for("teacher_subjects")
                )

            flash("Invalid teacher details.")
            return render_template("login.html")

        flash("Invalid user type.")

    return render_template("login.html")


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
# STUDENT DASHBOARD
# =========================

@app.route("/dashboard")
@student_required
def dashboard():

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT id, name, class_name, department
            FROM students
            WHERE id = %s
        """, (session["student_id"],))

        student = cur.fetchone()
    finally:
        conn.close()

    if not student:
        session.clear()
        flash("Student account no longer exists.")
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        student_name=student["name"],
        class_name=student["class_name"],
        department=student["department"]
    )


# =========================
# ADMIN DASHBOARD
# =========================

@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

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
            ORDER BY class_name, department, term, subject_name
        """)
        subjects = cur.fetchall()
    finally:
        conn.close()

    return render_template(
        "admin.html",
        admin=session["admin"],
        students=students,
        teachers=teachers,
        subjects=subjects
    )


# =========================
# REGISTER STUDENT
# =========================

@app.route(
    "/admin/register-student",
    methods=["POST"]
)
@admin_required
def register_student():

    name = normalize_name(
        request.form.get("name", "")
    )

    class_name = (
        request.form.get("class_name", "")
        .strip()
        .upper()
    )

    department = (
        request.form.get("department", "")
        .strip()
    )

    # Disabled JSS department fields may not be submitted.
    if is_jss(class_name):
        department = "General"

    password = request.form.get(
        "password", ""
    )

    valid_classes = {
        "JSS1", "JSS2", "JSS3",
        "SS1", "SS2", "SS3"
    }

    if not name or not class_name or not password:
        flash("Please fill all student registration fields.")
        return redirect(url_for("admin_dashboard"))

    if class_name not in valid_classes:
        flash("Invalid class selected.")
        return redirect(url_for("admin_dashboard"))

    if (
        class_name.startswith("SS")
        and department not in {
            "Science", "Art", "Commercial"
        }
    ):
        flash(
            "Select Science, Art or Commercial for SS classes."
        )
        return redirect(url_for("admin_dashboard"))

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO students
                (name, class_name, department, password)
            VALUES (%s, %s, %s, %s)
        """, (
            name,
            class_name,
            department,
            password
        ))

        conn.commit()
        flash(
            f"Student {name} registered successfully."
        )

    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        flash("A student with that name already exists.")

    except Exception as e:
        conn.rollback()
        print("Register student error:", repr(e))
        flash("Could not register student.")

    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


# =========================
# REGISTER TEACHER
# =========================

@app.route(
    "/admin/register-teacher",
    methods=["POST"]
)
@admin_required
def register_teacher():

    name = normalize_name(
        request.form.get("name", "")
    )

    password = request.form.get(
        "password", ""
    )

    if not name or not password:
        flash("Please fill all teacher fields.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO teachers
                (name, password)
            VALUES (%s, %s)
        """, (name, password))

        conn.commit()
        flash(
            f"Teacher {name} registered successfully."
        )

    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        flash("A teacher with that name already exists.")

    except Exception as e:
        conn.rollback()
        print("Register teacher error:", repr(e))
        flash("Could not register teacher.")

    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


# =========================
# ADD SUBJECT
# =========================

@app.route(
    "/admin/add-subject",
    methods=["POST"]
)
@admin_required
def add_subject():

    class_name = (
        request.form.get("class_name", "")
        .strip()
        .upper()
    )

    department = (
        request.form.get("department", "")
        .strip()
    )

    if is_jss(class_name):
        department = "General"

    term = (
        request.form.get("term", "")
        .strip()
    )

    subject_name = normalize_name(
        request.form.get("subject_name", "")
    )

    subject_link = (
        request.form.get("subject_link", "")
        .strip()
    )

    if not all([
        class_name,
        department,
        term,
        subject_name,
        subject_link
    ]):
        flash("Please fill all subject fields.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO subjects
                (
                    subject_name,
                    subject_link,
                    class_name,
                    department,
                    term
                )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            subject_name,
            subject_link,
            class_name,
            department,
            term
        ))

        conn.commit()
        flash(
            f"{subject_name} added successfully."
        )

    except Exception as e:
        conn.rollback()
        print("Add subject error:", repr(e))
        flash("Could not add subject.")

    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


# =========================
# DELETE SUBJECT
# =========================

@app.route(
    "/admin/delete-subject/<int:subject_id>"
)
@admin_required
def delete_subject(subject_id):

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM subjects
            WHERE id = %s
        """, (subject_id,))

        conn.commit()
        flash("Subject deleted.")

    except Exception as e:
        conn.rollback()
        print("Delete subject error:", repr(e))
        flash("Could not delete subject.")

    finally:
        conn.close()

    return redirect(url_for("admin_dashboard"))


# =========================
# UPLOAD RESULT
# =========================

@app.route(
    "/admin/upload-result",
    methods=["POST"]
)
@admin_required
def upload_result():

    student_name = normalize_name(
        request.form.get("student_name", "")
    )

    term = (
        request.form.get("term", "")
        .strip()
    )

    uploaded_file = request.files.get(
        "result_file"
    )

    if not student_name:
        flash("Enter the student's registered name.")
        return redirect(url_for("admin_dashboard"))

    if not term:
        flash("Please select the result term.")
        return redirect(url_for("admin_dashboard"))

    if (
        not uploaded_file
        or not uploaded_file.filename
    ):
        flash("Please select a result file.")
        return redirect(url_for("admin_dashboard"))

    original_filename = uploaded_file.filename
    extension = get_extension(original_filename)

    if extension not in ALLOWED_RESULT_EXTENSIONS:
        flash(
            "Unsupported file. Use PDF, XLSX, XLSM, XLS, ODS or an image."
        )
        return redirect(url_for("admin_dashboard"))

    # Find student
    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT id, name
            FROM students
            WHERE LOWER(TRIM(name))
                  = LOWER(TRIM(%s))
            LIMIT 1
        """, (student_name,))

        student = cur.fetchone()
    finally:
        conn.close()

    if not student:
        flash(
            f"No registered student was found with the name "
            f"'{student_name}'."
        )
        return redirect(url_for("admin_dashboard"))

    # Read uploaded file
    try:
        file_bytes = uploaded_file.read()

        if not file_bytes:
            flash("The uploaded file is empty.")
            return redirect(url_for("admin_dashboard"))

    except Exception as e:
        print("File read error:", repr(e))
        flash("Could not read the uploaded file.")
        return redirect(url_for("admin_dashboard"))

    # Validate modern Excel files.
    if extension in {"xlsx", "xlsm"}:
        try:
            workbook = load_workbook(
                io.BytesIO(file_bytes),
                read_only=True,
                data_only=False
            )
            workbook.close()

        except Exception as e:
            print("Excel validation error:", repr(e))
            flash(
                "The Excel file is invalid or damaged. "
                "Please save it again as .xlsx and upload it."
            )
            return redirect(url_for("admin_dashboard"))

    # Validate ODS files directly. No LibreOffice or Docker is required.
    if extension == "ods":
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as ods_zip:
                names = ods_zip.namelist()
                if "mimetype" not in names:
                    raise ValueError("ODS mimetype file is missing.")
                ods_mimetype = (
                    ods_zip.read("mimetype")
                    .decode("utf-8", errors="ignore")
                    .strip()
                )
                if ods_mimetype != "application/vnd.oasis.opendocument.spreadsheet":
                    raise ValueError(f"Invalid ODS mimetype: {ods_mimetype}")
        except zipfile.BadZipFile:
            flash(
                "The ODS file is damaged or is not a valid "
                "OpenDocument Spreadsheet."
            )
            return redirect(url_for("admin_dashboard"))
        except Exception as e:
            print("ODS validation error:", repr(e))
            flash("The uploaded file is not a valid ODS spreadsheet.")
            return redirect(url_for("admin_dashboard"))

    # Old binary XLS is still not parsed by this version.
    if extension == "xls":
        flash(
            "Old .xls files are not supported yet. "
            "Please save the file as .xlsx, .ods or PDF."
        )
        return redirect(url_for("admin_dashboard"))

    # Make a unique storage filename.
    base_name = original_filename.rsplit(
        ".",
        1
    )[0]

    # Keep only a safe filename.
    from werkzeug.utils import secure_filename
    safe_base = secure_filename(base_name)

    if not safe_base:
        safe_base = "student_result"

    storage_filename = (
        f"{student['id']}_"
        f"{int(datetime.utcnow().timestamp())}_"
        f"{safe_base}.{extension}"
    )

    storage_file_path = storage_path(
        storage_filename
    )

    content_type = (
        guess_type(original_filename)[0]
        or "application/octet-stream"
    )

    # Upload to Supabase Storage.
    try:
        upload_to_storage(
            file_bytes,
            storage_file_path,
            content_type
        )

    except Exception as e:
        print(
            "Supabase upload error:",
            repr(e)
        )
        flash(
            "The result could not be uploaded to Supabase Storage. "
            "Check your Supabase environment variables and bucket name."
        )
        return redirect(
            url_for("admin_dashboard")
        )

    # Save result record in PostgreSQL.
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO results
                (
                    student_id,
                    student_name,
                    filename,
                    original_filename,
                    term
                )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            student["id"],
            student["name"],
            storage_filename,
            original_filename,
            term
        ))

        conn.commit()

        flash(
            f"Result uploaded successfully for "
            f"{student['name']}."
        )

    except Exception as e:
        conn.rollback()

        print(
            "Save result record error:",
            repr(e)
        )

        delete_from_storage(
            storage_file_path
        )

        flash(
            "The file uploaded, but the result record "
            "could not be saved."
        )

    finally:
        conn.close()

    return redirect(
        url_for("admin_dashboard")
    )


# =========================
# DELETE STUDENT
# =========================

@app.route(
    "/admin/delete-student",
    methods=["POST"]
)
@admin_required
def delete_student():

    student_name = normalize_name(
        request.form.get("student_name", "")
    )

    if not student_name:
        flash("Enter the student's registered name.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT id, name
            FROM students
            WHERE LOWER(TRIM(name))
                  = LOWER(TRIM(%s))
            LIMIT 1
        """, (student_name,))

        student = cur.fetchone()

        if not student:
            flash("Student not found.")
            return redirect(url_for("admin_dashboard"))

        cur.execute("""
            SELECT filename
            FROM results
            WHERE student_id = %s
        """, (student["id"],))

        result_files = cur.fetchall()

        # Delete result rows first so this works even if the
        # existing database was created by an older version.
        cur.execute("""
            DELETE FROM results
            WHERE student_id = %s
        """, (student["id"],))

        cur.execute("""
            DELETE FROM students
            WHERE id = %s
        """, (student["id"],))

        conn.commit()

        for result in result_files:
            delete_from_storage(
                storage_path(result["filename"])
            )

        flash(
            f"Student {student['name']} and their results were deleted."
        )

    except Exception as e:
        conn.rollback()
        print("Delete student error:", repr(e))
        flash("Could not delete student.")

    finally:
        conn.close()

    return redirect(
        url_for("admin_dashboard")
    )


# =========================
# DELETE TEACHER
# =========================

@app.route(
    "/admin/delete-teacher",
    methods=["POST"]
)
@admin_required
def delete_teacher():

    teacher_name = normalize_name(
        request.form.get("teacher_name", "")
    )

    if not teacher_name:
        flash("Enter the teacher's registered name.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM teachers
            WHERE LOWER(TRIM(name))
                  = LOWER(TRIM(%s))
        """, (teacher_name,))

        if cur.rowcount == 0:
            flash("Teacher not found.")
        else:
            conn.commit()
            flash(
                f"Teacher {teacher_name} deleted."
            )

    except Exception as e:
        conn.rollback()
        print("Delete teacher error:", repr(e))
        flash("Could not delete teacher.")

    finally:
        conn.close()

    return redirect(
        url_for("admin_dashboard")
    )


# =========================
# ADD NEWS
# =========================

@app.route(
    "/admin/add-news",
    methods=["POST"]
)
@admin_required
def add_news():

    title = (
        request.form.get("title", "")
        .strip()
    )

    content = (
        request.form.get("content", "")
        .strip()
    )

    if not title or not content:
        flash("Enter both news title and content.")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO news
                (title, content, date, admin)
            VALUES (%s, %s, %s, %s)
        """, (
            title,
            content,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            session["admin"]
        ))

        conn.commit()
        flash("School news published successfully.")

    except Exception as e:
        conn.rollback()
        print("Add news error:", repr(e))
        flash("Could not publish news.")

    finally:
        conn.close()

    return redirect(
        url_for("admin_dashboard")
    )


# =========================
# STUDENT SUBJECTS
# =========================

@app.route("/subjects")
@student_required
def subjects_page():

    term = request.args.get(
        "term",
        "First Term"
    ).strip()

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT class_name, department
            FROM students
            WHERE id = %s
        """, (session["student_id"],))

        student = cur.fetchone()

        if not student:
            session.clear()
            flash("Student account no longer exists.")
            return redirect(url_for("login"))

        cur.execute("""
            SELECT *
            FROM subjects
            WHERE class_name = %s
              AND department = %s
              AND term = %s
            ORDER BY subject_name
        """, (
            student["class_name"],
            student["department"],
            term
        ))

        subject_rows = cur.fetchall()

    finally:
        conn.close()

    return render_template(
        "subjects.html",
        subjects=subject_rows,
        class_name=student["class_name"],
        department=student["department"],
        term=term
    )


# =========================
# STUDENT RESULTS
# =========================

@app.route("/results")
@student_required
def results():

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT
                id,
                term,
                original_filename,
                filename
            FROM results
            WHERE student_id = %s
            ORDER BY id DESC
        """, (session["student_id"],))

        result_rows = cur.fetchall()

    finally:
        conn.close()

    return render_template(
        "results.html",
        results=result_rows
    )


# =========================
# VIEW RESULT
# =========================

@app.route(
    "/view-result/<int:result_id>"
)
@student_required
def view_result(result_id):
    """Display a student's result securely from Supabase Storage."""
    conn = get_db()

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, student_id, student_name,
                   filename, original_filename, term
            FROM results
            WHERE id = %s
              AND student_id = %s
            LIMIT 1
        """, (
            result_id,
            session["student_id"]
        ))

        result = cur.fetchone()
    finally:
        conn.close()

    if not result:
        flash("Result not found.")
        return redirect(url_for("results"))

    extension = get_extension(result["filename"])

    # Browsers do not natively display ODS/XLSX/XLSM files.
    # Download the private file from Supabase and turn its cells into
    # an HTML table that the browser can display immediately.
    if extension in {"xlsx", "xlsm", "ods"}:
        try:
            file_bytes = download_from_storage(
                storage_path(result["filename"])
            )

            if not file_bytes:
                raise ValueError("The stored result file is empty.")

            if extension in {"xlsx", "xlsm"}:
                sheets = read_excel(file_bytes, extension)
            else:
                sheets = read_ods(file_bytes)

            return render_template(
                "view_result.html",
                result=result,
                file_type="spreadsheet",
                sheets=sheets
            )

        except Exception as e:
            print("Spreadsheet result view error:", repr(e))
            flash(
                "The spreadsheet result could not be opened. "
                "Please ask the administrator to re-upload the result."
            )
            return redirect(url_for("results"))

    # PDF/images are displayed through the authenticated result_file route.
    return render_template(
        "view_result.html",
        result=result,
        file_type="file",
        sheets=None
    )


# =========================
# RESULT FILE
# =========================

@app.route(
    "/result-file/<filename>"
)
@student_required
def result_file(filename):

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT *
            FROM results
            WHERE filename = %s
              AND student_id = %s
            LIMIT 1
        """, (
            filename,
            session["student_id"]
        ))

        result = cur.fetchone()

    finally:
        conn.close()

    if not result:
        flash("Result file not found.")
        return redirect(url_for("results"))

    extension = get_extension(
        result["filename"]
    )

    if extension in {"xlsx", "xlsm", "ods"}:
        return redirect(
            url_for(
                "view_result",
                result_id=result["id"]
            )
        )

    file_path = storage_path(
        result["filename"]
    )

    try:
        file_bytes = download_from_storage(
            file_path
        )
    except Exception as e:
        print(
            "Supabase download error:",
            repr(e)
        )
        flash(
            "The result file could not be loaded from Storage."
        )
        return redirect(url_for("results"))

    mimetype = (
        guess_type(
            result["original_filename"]
        )[0]
        or "application/octet-stream"
    )

    return send_file(
        io.BytesIO(file_bytes),
        mimetype=mimetype,
        download_name=result["original_filename"],
        as_attachment=False
    )


# =========================
# SCHOOL NEWS
# =========================

@app.route("/news")
@student_required
def news():

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT *
            FROM news
            ORDER BY id DESC
        """)

        news_rows = cur.fetchall()

    finally:
        conn.close()

    return render_template(
        "news.html",
        news=news_rows
    )


# =========================
# TEACHER PANEL
# =========================

@app.route("/teacher")
@app.route("/teacher/subjects")
def teacher_subjects():

    if "teacher_id" not in session:
        flash("Please log in as a teacher.")
        return redirect(url_for("login"))

    selected_class = (
        request.args.get(
            "class_name",
            ""
        )
        .strip()
        .upper()
    )

    selected_department = (
        request.args.get(
            "department",
            ""
        )
        .strip()
    )

    selected_term = (
        request.args.get(
            "term",
            ""
        )
        .strip()
    )

    # The teacher HTML disables department for JSS,
    # so the browser may not send it.
    if is_jss(selected_class):
        selected_department = "General"

    conn = get_db()

    try:
        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT DISTINCT class_name
            FROM subjects
            ORDER BY class_name
        """)

        classes = cur.fetchall()

        subject_rows = []

        if (
            selected_class
            and selected_department
            and selected_term
        ):

            cur.execute("""
                SELECT *
                FROM subjects
                WHERE class_name = %s
                  AND department = %s
                  AND term = %s
                ORDER BY subject_name
            """, (
                selected_class,
                selected_department,
                selected_term
            ))

            subject_rows = cur.fetchall()

    finally:
        conn.close()

    return render_template(
        "teacher.html",
        teacher_name=session["teacher_name"],
        classes=classes,
        subjects=subject_rows,
        selected_class=selected_class,
        selected_department=selected_department,
        selected_term=selected_term
    )


# =========================
# ERRORS
# =========================

@app.errorhandler(413)
def too_large(error):
    flash("The uploaded file is too large.")
    return redirect(
        url_for("admin_dashboard")
    )


# =========================
# RUN
# =========================

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
