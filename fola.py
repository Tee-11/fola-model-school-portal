from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_file
)

import os
import io
import mimetypes
import tempfile
import subprocess

import psycopg2
from psycopg2.extras import RealDictCursor

from supabase import create_client, Client

from functools import wraps
from werkzeug.utils import secure_filename

from data import ADMINS



app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "fola_model_school_change_this_secret"
)



BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)



DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Add DATABASE_URL to your Render Environment Variables."
    )


class Database:

    def __init__(self):

        self.connection = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=RealDictCursor
        )

        self.cursor = self.connection.cursor()


    def execute(self, query, parameters=None):

        if parameters is None:

            self.cursor.execute(query)

        else:

            self.cursor.execute(
                query,
                parameters
            )

        return self.cursor


    def commit(self):

        self.connection.commit()


    def rollback(self):

        self.connection.rollback()


    def close(self):

        try:

            self.cursor.close()

        finally:

            self.connection.close()


def get_db():

    return Database()



SUPABASE_URL = os.environ.get(
    "SUPABASE_URL"
)

SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY"
)

if not SUPABASE_URL:

    raise RuntimeError(
        "SUPABASE_URL is not set. "
        "Add SUPABASE_URL to your Render Environment Variables."
    )


if not SUPABASE_KEY:

    raise RuntimeError(
        "SUPABASE_KEY is not set. "
        "Add SUPABASE_KEY to your Render Environment Variables."
    )


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)



SUPABASE_BUCKET = "school files"



TEMP_FOLDER = os.path.join(
    tempfile.gettempdir(),
    "fola_school_portal"
)


os.makedirs(
    TEMP_FOLDER,
    exist_ok=True
)



def init_db():

    db = get_db()

    try:

        db.execute("""
            CREATE TABLE IF NOT EXISTS students (

                id SERIAL PRIMARY KEY,

                name TEXT NOT NULL UNIQUE,

                class_name TEXT NOT NULL,

                department TEXT NOT NULL,

                password TEXT NOT NULL

            )
        """)


        db.execute("""
            CREATE TABLE IF NOT EXISTS teachers (

                id SERIAL PRIMARY KEY,

                name TEXT NOT NULL UNIQUE,

                password TEXT NOT NULL

            )
        """)


        db.execute("""
            CREATE TABLE IF NOT EXISTS subjects (

                id SERIAL PRIMARY KEY,

                subject_name TEXT NOT NULL,

                subject_link TEXT NOT NULL,

                class_name TEXT NOT NULL,

                department TEXT NOT NULL,

                term TEXT NOT NULL

            )
        """)


        db.execute("""
            CREATE TABLE IF NOT EXISTS results (

                id SERIAL PRIMARY KEY,

                student_id INTEGER NOT NULL,

                student_name TEXT NOT NULL,

                filename TEXT NOT NULL,

                original_filename TEXT NOT NULL,

                term TEXT NOT NULL,

                FOREIGN KEY(student_id)
                    REFERENCES students(id)

            )
        """)


        db.execute("""
            CREATE TABLE IF NOT EXISTS news (

                id SERIAL PRIMARY KEY,

                title TEXT NOT NULL,

                content TEXT NOT NULL,

                date TEXT NOT NULL,

                admin TEXT NOT NULL

            )
        """)


        db.commit()


    except Exception:

        db.rollback()

        raise


    finally:

        db.close()


init_db()



def current_admin():

    return session.get("admin")


def is_admin():

    return "admin" in session


def is_student():

    return "student_id" in session


def is_teacher():

    return "teacher_id" in session


def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not is_admin():

            return redirect(
                url_for("login")
            )

        return function(*args, **kwargs)

    return wrapper


def student_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not is_student():

            return redirect(
                url_for("login")
            )

        return function(*args, **kwargs)

    return wrapper


def teacher_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not is_teacher():

            return redirect(
                url_for("login")
            )

        return function(*args, **kwargs)

    return wrapper



def get_mimetype(filename):

    mimetype, _ = mimetypes.guess_type(
        filename
    )

    if mimetype:

        return mimetype


    extension = os.path.splitext(
        filename
    )[1].lower()


    mime_types = {

        ".pdf": "application/pdf",

        ".xlsx": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),

        ".xls": (
            "application/vnd.ms-excel"
        ),

        ".ods": (
            "application/vnd.oasis.opendocument.spreadsheet"
        ),

        ".png": "image/png",

        ".jpg": "image/jpeg",

        ".jpeg": "image/jpeg",

        ".gif": "image/gif",

        ".webp": "image/webp"

    }


    return mime_types.get(
        extension,
        "application/octet-stream"
    )


def upload_file_to_supabase(
    local_filepath,
    storage_path
):

    mimetype = get_mimetype(
        local_filepath
    )


    with open(
        local_filepath,
        "rb"
    ) as file:

        file_data = file.read()


    response = (
        supabase
        .storage
        .from_(SUPABASE_BUCKET)
        .upload(
            path=storage_path,
            file=file_data,
            file_options={
                "content-type": mimetype,
                "cache-control": "3600",
                "upsert": "true"
            }
        )
    )


    return response


def download_file_from_supabase(
    storage_path
):

    response = (
        supabase
        .storage
        .from_(SUPABASE_BUCKET)
        .download(
            storage_path
        )
    )


    return response



@app.route(
    "/",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()


        password = request.form.get(
            "password",
            ""
        ).strip()


        user_type = request.form.get(
            "user_type",
            "student"
        )



        if user_type == "admin":

            admin_found = None

            admin_password = None


            for admin_name, stored_password in ADMINS.items():

                if (
                    name.lower()
                    == admin_name.lower()
                ):

                    admin_found = admin_name

                    admin_password = stored_password

                    break


            if (
                admin_found
                and password == admin_password
            ):

                session.clear()

                session["admin"] = admin_found

                return redirect(
                    url_for("admin")
                )


            flash(
                "Invalid administrator name or password."
            )

            return redirect(
                url_for("login")
            )



        if user_type == "teacher":

            db = get_db()

            try:

                teacher = db.execute("""
                    SELECT *
                    FROM teachers
                    WHERE LOWER(name) = LOWER(%s)
                    AND password = %s
                """, (
                    name,
                    password
                )).fetchone()

            finally:

                db.close()


            if teacher:

                session.clear()

                session["teacher_id"] = (
                    teacher["id"]
                )

                session["teacher_name"] = (
                    teacher["name"]
                )

                return redirect(
                    url_for("teacher")
                )


            flash(
                "Invalid teacher name or password."
            )

            return redirect(
                url_for("login")
            )



        db = get_db()

        try:

            student = db.execute("""
                SELECT *
                FROM students
                WHERE LOWER(name) = LOWER(%s)
                AND password = %s
            """, (
                name,
                password
            )).fetchone()

        finally:

            db.close()


        if student:

            session.clear()

            session["student_id"] = (
                student["id"]
            )

            session["student_name"] = (
                student["name"]
            )

            session["class_name"] = (
                student["class_name"]
            )

            session["department"] = (
                student["department"]
            )

            return redirect(
                url_for("dashboard")
            )


        flash(
            "Invalid student name or password."
        )

        return redirect(
            url_for("login")
        )


    return render_template(
        "login.html"
    )



@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )



@app.route("/admin")
@admin_required
def admin():

    db = get_db()

    try:

        students = db.execute("""
            SELECT *
            FROM students
            ORDER BY name
        """).fetchall()


        teachers = db.execute("""
            SELECT *
            FROM teachers
            ORDER BY name
        """).fetchall()


        subjects = db.execute("""
            SELECT *
            FROM subjects
            ORDER BY
                class_name,
                department,
                term,
                subject_name
        """).fetchall()


        news = db.execute("""
            SELECT *
            FROM news
            ORDER BY id DESC
        """).fetchall()

    finally:

        db.close()


    return render_template(
        "admin.html",
        admin=current_admin(),
        students=students,
        teachers=teachers,
        subjects=subjects,
        news=news
    )



@app.route(
    "/admin/register-student",
    methods=["POST"]
)
@admin_required
def register_student():

    name = request.form.get(
        "name",
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


    password = request.form.get(
        "password",
        ""
    ).strip()


    if (
        not name
        or not class_name
        or not password
    ):

        flash(
            "Please complete all student information."
        )

        return redirect(
            url_for("admin")
        )


    if class_name.upper().startswith("JSS"):

        department = "General"


    if not department:

        flash(
            "Please select a department."
        )

        return redirect(
            url_for("admin")
        )


    db = get_db()

    try:

        db.execute("""
            INSERT INTO students
            (
                name,
                class_name,
                department,
                password
            )

            VALUES (%s, %s, %s, %s)
        """, (
            name,
            class_name,
            department,
            password
        ))


        db.commit()

        flash(
            "Student registered successfully."
        )


    except psycopg2.IntegrityError:

        db.rollback()

        flash(
            "A student with this registered name already exists."
        )


    finally:

        db.close()


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/register-teacher",
    methods=["POST"]
)
@admin_required
def register_teacher():

    name = request.form.get(
        "name",
        ""
    ).strip()


    password = request.form.get(
        "password",
        ""
    ).strip()


    if not name or not password:

        flash(
            "Please enter the teacher name and password."
        )

        return redirect(
            url_for("admin")
        )


    db = get_db()

    try:

        db.execute("""
            INSERT INTO teachers
            (
                name,
                password
            )

            VALUES (%s, %s)
        """, (
            name,
            password
        ))


        db.commit()

        flash(
            "Teacher registered successfully."
        )


    except psycopg2.IntegrityError:

        db.rollback()

        flash(
            "A teacher with this registered name already exists."
        )


    finally:

        db.close()


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/delete-student",
    methods=["POST"]
)
@admin_required
def delete_student_by_name():

    name = request.form.get(
        "student_name",
        ""
    ).strip()


    if not name:

        flash(
            "Enter the student's registered name."
        )

        return redirect(
            url_for("admin")
        )


    db = get_db()

    try:

        student = db.execute("""
            SELECT *
            FROM students
            WHERE LOWER(name) = LOWER(%s)
        """, (
            name,
        )).fetchone()


        if not student:

            flash(
                "Student not found."
            )

            return redirect(
                url_for("admin")
            )


        db.execute("""
            DELETE FROM results
            WHERE student_id = %s
        """, (
            student["id"],
        ))


        db.execute("""
            DELETE FROM students
            WHERE id = %s
        """, (
            student["id"],
        ))


        db.commit()


    finally:

        db.close()


    flash(
        f"Student '{student['name']}' deleted successfully."
    )


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/delete-teacher",
    methods=["POST"]
)
@admin_required
def delete_teacher_by_name():

    name = request.form.get(
        "teacher_name",
        ""
    ).strip()


    if not name:

        flash(
            "Enter the teacher's registered name."
        )

        return redirect(
            url_for("admin")
        )


    db = get_db()

    try:

        teacher = db.execute("""
            SELECT *
            FROM teachers
            WHERE LOWER(name) = LOWER(%s)
        """, (
            name,
        )).fetchone()


        if not teacher:

            flash(
                "Teacher not found."
            )

            return redirect(
                url_for("admin")
            )


        db.execute("""
            DELETE FROM teachers
            WHERE id = %s
        """, (
            teacher["id"],
        ))


        db.commit()


    finally:

        db.close()


    flash(
        f"Teacher '{teacher['name']}' deleted successfully."
    )


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/add-subject",
    methods=["POST"]
)
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


    if class_name.upper().startswith("JSS"):

        department = "General"


    if (
        not subject_name
        or not subject_link
        or not class_name
        or not department
        or not term
    ):

        flash(
            "Please complete all subject information."
        )

        return redirect(
            url_for("admin")
        )


    db = get_db()

    try:

        db.execute("""
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


        db.commit()


    finally:

        db.close()


    flash(
        "Subject added successfully."
    )


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/delete-subject/<int:subject_id>"
)
@admin_required
def delete_subject(subject_id):

    db = get_db()

    try:

        db.execute("""
            DELETE FROM subjects
            WHERE id = %s
        """, (
            subject_id,
        ))


        db.commit()


    finally:

        db.close()


    flash(
        "Subject deleted successfully."
    )


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/upload-result",
    methods=["POST"]
)
@admin_required
def upload_result():

    student_name = request.form.get(
        "student_name",
        ""
    ).strip()


    term = request.form.get(
        "term",
        "First Term"
    ).strip()


    result_file = request.files.get(
        "result_file"
    )


    if not student_name:

        flash(
            "Enter the student's registered name."
        )

        return redirect(
            url_for("admin")
        )


    if (
        not result_file
        or not result_file.filename
    ):

        flash(
            "Please select a result file."
        )

        return redirect(
            url_for("admin")
        )


    original_filename = (
        result_file.filename
    )


    safe_filename = secure_filename(
        original_filename
    )


    if not safe_filename:

        flash(
            "Invalid result filename."
        )

        return redirect(
            url_for("admin")
        )


    allowed_extensions = {

        ".pdf",

        ".xlsx",

        ".xls",

        ".ods",

        ".png",

        ".jpg",

        ".jpeg",

        ".gif",

        ".webp"

    }


    extension = os.path.splitext(
        safe_filename
    )[1].lower()


    if extension not in allowed_extensions:

        flash(
            "Unsupported result file type."
        )

        return redirect(
            url_for("admin")
        )


    db = get_db()


    try:

        student = db.execute("""
            SELECT *
            FROM students
            WHERE LOWER(name) = LOWER(%s)
        """, (
            student_name,
        )).fetchone()


        if not student:

            flash(
                "Student with that registered name was not found."
            )

            return redirect(
                url_for("admin")
            )



        stored_filename = (
            str(student["id"])
            + "_"
            + safe_filename
        )


        local_input_path = os.path.join(
            TEMP_FOLDER,
            stored_filename
        )


        result_file.save(
            local_input_path
        )


        final_local_path = (
            local_input_path
        )


        final_filename = (
            stored_filename
        )



        spreadsheet_extensions = {

            ".xlsx",

            ".xls",

            ".ods"

        }


        if extension in spreadsheet_extensions:

            pdf_filename = (
                os.path.splitext(
                    stored_filename
                )[0]
                + ".pdf"
            )


            pdf_path = os.path.join(
                TEMP_FOLDER,
                pdf_filename
            )


            if os.path.exists(pdf_path):

                os.remove(pdf_path)


            try:

                subprocess.run(
                    [
                        "libreoffice",

                        "--headless",

                        "--convert-to",
                        "pdf",

                        "--outdir",
                        TEMP_FOLDER,

                        local_input_path
                    ],

                    check=True,

                    stdout=subprocess.PIPE,

                    stderr=subprocess.PIPE,

                    timeout=120
                )


                if not os.path.exists(
                    pdf_path
                ):

                    raise RuntimeError(
                        "LibreOffice did not create the PDF."
                    )


                if os.path.exists(
                    local_input_path
                ):

                    os.remove(
                        local_input_path
                    )


                final_local_path = pdf_path

                final_filename = pdf_filename


            except Exception as error:

                if os.path.exists(
                    local_input_path
                ):

                    os.remove(
                        local_input_path
                    )


                print(
                    "LibreOffice conversion error:",
                    error
                )


                flash(
                    "The spreadsheet could not be converted to PDF."
                )

                return redirect(
                    url_for("admin")
                )



        storage_path = (
            "results/"
            + final_filename
        )


        try:

            upload_file_to_supabase(
                final_local_path,
                storage_path
            )


        except Exception as error:

            print(
                "Supabase upload error:",
                error
            )


            if os.path.exists(
                final_local_path
            ):

                os.remove(
                    final_local_path
                )


            flash(
                "The result could not be uploaded to secure storage."
            )

            return redirect(
                url_for("admin")
            )



        if os.path.exists(
            final_local_path
        ):

            os.remove(
                final_local_path
            )



        db.execute("""
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
            final_filename,
            original_filename,
            term
        ))


        db.commit()


    except Exception as error:

        db.rollback()

        print(
            "Result upload error:",
            error
        )

        flash(
            "An error occurred while uploading the result."
        )

        return redirect(
            url_for("admin")
        )


    finally:

        db.close()


    flash(
        "Student result uploaded successfully."
    )


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/add-news",
    methods=["POST"]
)
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

        flash(
            "Please enter the news title and content."
        )

        return redirect(
            url_for("admin")
        )


    from datetime import datetime


    date = datetime.now().strftime(
        "%d %B %Y, %I:%M %p"
    )


    db = get_db()

    try:

        db.execute("""
            INSERT INTO news
            (
                title,
                content,
                date,
                admin
            )

            VALUES (%s, %s, %s, %s)
        """, (
            title,
            content,
            date,
            current_admin()
        ))


        db.commit()


    finally:

        db.close()


    flash(
        "School news published successfully."
    )


    return redirect(
        url_for("admin")
    )



@app.route(
    "/admin/delete-news/<int:news_id>"
)
@admin_required
def delete_news(news_id):

    db = get_db()

    try:

        db.execute("""
            DELETE FROM news
            WHERE id = %s
        """, (
            news_id,
        ))


        db.commit()


    finally:

        db.close()


    flash(
        "School news deleted successfully."
    )


    return redirect(
        url_for("admin")
    )



@app.route("/dashboard")
@student_required
def dashboard():

    return render_template(
        "dashboard.html",

        student_name=session.get(
            "student_name"
        ),

        class_name=session.get(
            "class_name"
        ),

        department=session.get(
            "department"
        )
    )



@app.route("/subjects")
@student_required
def subjects():

    class_name = session.get(
        "class_name"
    )


    department = session.get(
        "department"
    )


    term = request.args.get(
        "term",
        "First Term"
    )


    if not class_name:

        flash(
            "Your class information was not found. Please log in again."
        )

        session.clear()

        return redirect(
            url_for("login")
        )


    if class_name.upper().startswith("JSS"):

        department = "General"


    db = get_db()

    try:

        subjects = db.execute("""
            SELECT *
            FROM subjects

            WHERE class_name = %s

            AND department = %s

            AND term = %s

            ORDER BY subject_name
        """, (
            class_name,
            department,
            term
        )).fetchall()


    finally:

        db.close()


    return render_template(
        "subjects.html",

        subjects=subjects,

        class_name=class_name,

        department=department,

        term=term
    )



@app.route("/results")
@student_required
def results():

    student_id = session.get(
        "student_id"
    )


    db = get_db()

    try:

        results = db.execute("""
            SELECT *
            FROM results

            WHERE student_id = %s

            ORDER BY id DESC
        """, (
            student_id,
        )).fetchall()


    finally:

        db.close()


    return render_template(
        "results.html",
        results=results
    )



@app.route(
    "/result/<int:result_id>"
)
@student_required
def view_result(result_id):

    student_id = session.get(
        "student_id"
    )


    db = get_db()

    try:

        result = db.execute("""
            SELECT *
            FROM results

            WHERE id = %s

            AND student_id = %s
        """, (
            result_id,
            student_id
        )).fetchone()


    finally:

        db.close()


    if not result:

        flash(
            "Result not found."
        )

        return redirect(
            url_for("results")
        )


    return render_template(
        "view_result.html",

        result=result,

        file_type="file",

        sheets=None
    )



@app.route(
    "/result-file/<filename>"
)
@student_required
def result_file(filename):

    student_id = session.get(
        "student_id"
    )


    db = get_db()

    try:

        result = db.execute("""
            SELECT *
            FROM results

            WHERE filename = %s

            AND student_id = %s
        """, (
            filename,
            student_id
        )).fetchone()


    finally:

        db.close()



    if not result:

        return "Result not found.", 404



    storage_path = (
        "results/"
        + result["filename"]
    )


    try:

        file_data = (
            download_file_from_supabase(
                storage_path
            )
        )


    except Exception as error:

        print(
            "Supabase download error:",
            error
        )

        return (
            "The result file could not be loaded.",
            500
        )


    mimetype = get_mimetype(
        result["filename"]
    )


    return send_file(
        io.BytesIO(file_data),

        mimetype=mimetype,

        download_name=result[
            "original_filename"
        ],

        as_attachment=False
    )


@app.route("/news")
@student_required
def news():

    db = get_db()

    try:

        news_items = db.execute("""
            SELECT *
            FROM news

            ORDER BY id DESC
        """).fetchall()


    finally:

        db.close()


    return render_template(
        "news.html",
        news=news_items
    )



@app.route("/teacher")
@teacher_required
def teacher():

    db = get_db()

    try:

        classes = db.execute("""
            SELECT DISTINCT class_name
            FROM subjects

            ORDER BY class_name
        """).fetchall()


    finally:

        db.close()


    return render_template(
        "teacher.html",

        classes=classes,

        teacher_name=session.get(
            "teacher_name"
        ),

        selected_class="",

        selected_department="",

        selected_term="",

        subjects=[]
    )



@app.route(
    "/teacher/subjects"
)
@teacher_required
def teacher_subjects():

    class_name = request.args.get(
        "class_name",
        ""
    ).strip()


    department = request.args.get(
        "department",
        ""
    ).strip()


    term = request.args.get(
        "term",
        ""
    ).strip()


    if class_name.upper().startswith("JSS"):

        department = "General"


    db = get_db()

    try:

        classes = db.execute("""
            SELECT DISTINCT class_name
            FROM subjects

            ORDER BY class_name
        """).fetchall()


        subjects = []


        if (
            class_name
            and department
            and term
        ):

            subjects = db.execute("""
                SELECT *
                FROM subjects

                WHERE class_name = %s

                AND department = %s

                AND term = %s

                ORDER BY subject_name
            """, (
                class_name,
                department,
                term
            )).fetchall()


    finally:

        db.close()


    return render_template(
        "teacher.html",

        classes=classes,

        subjects=subjects,

        teacher_name=session.get(
            "teacher_name"
        ),

        selected_class=class_name,

        selected_department=department,

        selected_term=term
    )



if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),

        debug=False
    )
