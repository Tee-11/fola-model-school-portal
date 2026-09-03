import os
import io
import mimetypes
import secrets
from functools import wraps
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename

from dotenv import load_dotenv

from supabase import create_client

from data import ADMIN_NAME, ADMIN_PASSWORD


load_dotenv()


app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    secrets.token_hex(32)
)

app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


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


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


def db():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def fetch_one(sql, params=()):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def fetch_all(sql, params=()):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def execute(sql, params=()):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def current_user():
    role = session.get("role")
    user_id = session.get("user_id")

    if role == "student" and user_id:
        return fetch_one(
            "SELECT * FROM students WHERE id=%s",
            (user_id,)
        )

    if role == "teacher" and user_id:
        return fetch_one(
            "SELECT * FROM teachers WHERE id=%s",
            (user_id,)
        )

    if role == "admin":
        return {
            "name": session.get(
                "admin_name",
                ADMIN_NAME
            )
        }

    return None


def login_required(*roles):
    def decorator(fn):

        @wraps(fn)
        def wrapper(*args, **kwargs):

            if session.get("role") not in roles:

                flash(
                    "Please log in first.",
                    "error"
                )

                return redirect(
                    url_for("login")
                )

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def unique_storage_path(folder, filename):

    safe_filename = secure_filename(
        filename
    )

    if not safe_filename:
        raise ValueError(
            "Please choose a valid file."
        )

    token = secrets.token_hex(8)

    return (
        f"{folder}/"
        f"{token}_"
        f"{safe_filename}"
    )


def upload_to_storage(
    file_storage,
    folder
):

    filename = secure_filename(
        file_storage.filename or ""
    )

    if not filename:
        raise ValueError(
            "Please choose a file."
        )

    path = unique_storage_path(
        folder,
        filename
    )

    content = file_storage.read()

    content_type = (
        file_storage.mimetype
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )

    supabase.storage.from_(
        SUPABASE_BUCKET
    ).upload(
        path,
        content,
        {
            "content-type": content_type,
            "upsert": "false"
        }
    )

    return (
        path,
        filename,
        content_type
    )


def signed_storage_url(
    path,
    seconds=3600
):

    result = (
        supabase
        .storage
        .from_(SUPABASE_BUCKET)
        .create_signed_url(
            path,
            seconds
        )
    )

    if isinstance(result, dict):

        return (
            result.get("signedURL")
            or result.get("signedUrl")
        )

    return (
        getattr(
            result,
            "signed_url",
            None
        )
        or
        getattr(
            result,
            "signedURL",
            None
        )
    )


def delete_storage(path):

    if not path:
        return

    try:

        supabase.storage.from_(
            SUPABASE_BUCKET
        ).remove(
            [path]
        )

    except Exception:

        pass


@app.route("/")
def index():

    role = session.get("role")

    if role == "admin":
        return redirect(
            url_for("admin_dashboard")
        )

    if role == "student":
        return redirect(
            url_for("student_dashboard")
        )

    if role == "teacher":
        return redirect(
            url_for("teacher_dashboard")
        )

    return redirect(
        url_for("login")
    )


@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        role = (
            request.form
            .get("role", "")
            .strip()
            .lower()
        )

        name = (
            request.form
            .get("name", "")
            .strip()
        )

        password = request.form.get(
            "password",
            ""
        )

        if not role or not name or not password:

            flash(
                "Select a role and enter your name and password.",
                "error"
            )

            return render_template(
                "login.html"
            )

        session.clear()

        if role == "admin":

            if (
                name.casefold()
                ==
                ADMIN_NAME.casefold()
                and
                secrets.compare_digest(
                    password,
                    ADMIN_PASSWORD
                )
            ):

                session["role"] = "admin"
                session["user_id"] = "master_admin"
                session["admin_name"] = ADMIN_NAME
                session["is_master_admin"] = True

                return redirect(
                    url_for(
                        "admin_dashboard"
                    )
                )

            admin = fetch_one(
                """
                SELECT *
                FROM administrators
                WHERE LOWER(name)=LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if (
                admin
                and
                check_password_hash(
                    admin["password_hash"],
                    password
                )
            ):

                session["role"] = "admin"
                session["user_id"] = admin["id"]
                session["admin_name"] = admin["name"]
                session["is_master_admin"] = False

                return redirect(
                    url_for(
                        "admin_dashboard"
                    )
                )

        elif role == "student":

            user = fetch_one(
                """
                SELECT *
                FROM students
                WHERE LOWER(name)=LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if (
                user
                and
                check_password_hash(
                    user["password_hash"],
                    password
                )
            ):

                session["role"] = "student"
                session["user_id"] = user["id"]

                return redirect(
                    url_for(
                        "student_dashboard"
                    )
                )

        elif role == "teacher":

            user = fetch_one(
                """
                SELECT *
                FROM teachers
                WHERE LOWER(name)=LOWER(%s)
                LIMIT 1
                """,
                (name,)
            )

            if (
                user
                and
                check_password_hash(
                    user["password_hash"],
                    password
                )
            ):

                session["role"] = "teacher"
                session["user_id"] = user["id"]

                return redirect(
                    url_for(
                        "teacher_dashboard"
                    )
                )

        flash(
            "Invalid login details.",
            "error"
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


@app.route("/student")
@login_required("student")
def student_dashboard():

    student = current_user()

    return render_template(
        "student_dashboard.html",
        student=student
    )


@app.route("/student/subjects")
@login_required("student")
def student_subjects():

    student = current_user()

    term = request.args.get(
        "term",
        "First Term"
    )

    subjects = fetch_all(
        """
        SELECT *
        FROM subjects
        WHERE LOWER(class_name)=LOWER(%s)
        AND LOWER(department)=LOWER(%s)
        AND term=%s
        ORDER BY name
        """,
        (
            student["class_name"],
            student["department"],
            term
        )
    )

    return render_template(
        "subjects.html",
        title=f"Subjects - {term}",
        subjects=subjects,
        term=term,
        back_url=url_for(
            "student_dashboard"
        )
    )


@app.route("/student/results")
@login_required("student")
def student_results():

    student = current_user()

    results = fetch_all(
        """
        SELECT *
        FROM results
        WHERE student_id=%s
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

    for result in results:

        grouped.setdefault(
            result["term"],
            []
        ).append(result)

    return render_template(
        "results.html",
        grouped=grouped,
        back_url=url_for(
            "student_dashboard"
        )
    )


@app.route("/student/news")
@login_required("student")
def student_news():

    news = fetch_all(
        """
        SELECT *
        FROM news
        ORDER BY created_at DESC
        """
    )

    return render_template(
        "news.html",
        news=news,
        back_url=url_for(
            "student_dashboard"
        )
    )


@app.route("/teacher")
@login_required("teacher")
def teacher_dashboard():

    classes = fetch_all(
        """
        SELECT DISTINCT class_name
        FROM subjects
        ORDER BY class_name
        """
    )

    return render_template(
        "teacher_dashboard.html",
        classes=classes
    )


@app.route("/teacher/subjects")
@login_required("teacher")
def teacher_subjects():

    class_name = (
        request.args
        .get("class_name", "")
        .strip()
    )

    department = (
        request.args
        .get(
            "department",
            "General"
        )
        .strip()
    )

    term = request.args.get(
        "term",
        "First Term"
    )

    subjects = []

    if class_name:

        subjects = fetch_all(
            """
            SELECT *
            FROM subjects
            WHERE LOWER(class_name)=LOWER(%s)
            AND LOWER(department)=LOWER(%s)
            AND term=%s
            ORDER BY name
            """,
            (
                class_name,
                department,
                term
            )
        )

    return render_template(
        "subjects.html",
        title=(
            f"{class_name or 'Class'} - "
            f"{department} - "
            f"{term}"
        ),
        subjects=subjects,
        term=term,
        back_url=url_for(
            "teacher_dashboard"
        )
    )


@app.route("/admin")
@login_required("admin")
def admin_dashboard():

    return render_template(
        "admin_dashboard.html"
    )


@app.route(
    "/admin/administrators",
    methods=["GET", "POST"]
)
@login_required("admin")
def admin_administrators():

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "register":

            name = (
                request.form
                .get("name", "")
                .strip()
            )

            password = request.form.get(
                "password",
                ""
            )

            if not name or not password:

                flash(
                    "Administrator name and password are required.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_administrators"
                    )
                )

            if (
                name.casefold()
                ==
                ADMIN_NAME.casefold()
            ):

                flash(
                    "That name is reserved for the master administrator.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_administrators"
                    )
                )

            existing_admin = fetch_one(
                """
                SELECT id
                FROM administrators
                WHERE LOWER(name)=LOWER(%s)
                """,
                (name,)
            )

            if existing_admin:

                flash(
                    "An administrator with that name already exists.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_administrators"
                    )
                )

            execute(
                """
                INSERT INTO administrators
                (
                    name,
                    password_hash
                )
                VALUES (%s,%s)
                """,
                (
                    name,
                    generate_password_hash(
                        password
                    )
                )
            )

            flash(
                f"Administrator '{name}' registered successfully.",
                "success"
            )

        elif action == "delete":

            admin_id = request.form.get(
                "admin_id"
            )

            admin = fetch_one(
                """
                SELECT *
                FROM administrators
                WHERE id=%s
                """,
                (admin_id,)
            )

            if not admin:

                flash(
                    "Administrator not found.",
                    "error"
                )

            else:

                execute(
                    """
                    DELETE FROM administrators
                    WHERE id=%s
                    """,
                    (admin_id,)
                )

                flash(
                    f"Administrator '{admin['name']}' deleted.",
                    "success"
                )

    administrators = fetch_all(
        """
        SELECT id,name,created_at
        FROM administrators
        ORDER BY name
        """
    )

    return render_template(
        "admin_administrators.html",
        administrators=administrators
    )


@app.route(
    "/admin/students",
    methods=["GET", "POST"]
)
@login_required("admin")
def admin_students():

    edit_student = None
    searched = False
    searched_student = None

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "register":

            name = (
                request.form
                .get("name", "")
                .strip()
            )

            class_name = (
                request.form
                .get(
                    "class_name",
                    ""
                )
                .strip()
            )

            department = (
                request.form
                .get(
                    "department",
                    "General"
                )
                .strip()
            )

            password = request.form.get(
                "password",
                ""
            )

            if not all(
                [
                    name,
                    class_name,
                    department,
                    password
                ]
            ):

                flash(
                    "Fill all student registration fields.",
                    "error"
                )

            elif fetch_one(
                """
                SELECT id
                FROM students
                WHERE LOWER(name)=LOWER(%s)
                """,
                (name,)
            ):

                flash(
                    "A student with that name is already registered.",
                    "error"
                )

            else:

                execute(
                    """
                    INSERT INTO students
                    (
                        name,
                        class_name,
                        department,
                        password_hash
                    )
                    VALUES (%s,%s,%s,%s)
                    """,
                    (
                        name,
                        class_name,
                        department,
                        generate_password_hash(
                            password
                        )
                    )
                )

                flash(
                    "Student registered successfully.",
                    "success"
                )

        elif action == "edit_by_name":

            lookup_name = (
                request.form
                .get(
                    "lookup_name",
                    ""
                )
                .strip()
            )

            searched = True

            searched_student = fetch_one(
                """
                SELECT
                    id,
                    name,
                    class_name,
                    department
                FROM students
                WHERE LOWER(name)=LOWER(%s)
                LIMIT 1
                """,
                (lookup_name,)
            )

            if searched_student:

                edit_student = searched_student

            else:

                flash(
                    "No registered student was found with that name.",
                    "error"
                )

        elif action == "edit":

            student_id = request.form.get(
                "student_id"
            )

            student = fetch_one(
                """
                SELECT *
                FROM students
                WHERE id=%s
                """,
                (student_id,)
            )

            if not student:

                flash(
                    "Student not found.",
                    "error"
                )

            else:

                name = (
                    request.form
                    .get("name", "")
                    .strip()
                )

                class_name = (
                    request.form
                    .get(
                        "class_name",
                        ""
                    )
                    .strip()
                )

                department = (
                    request.form
                    .get(
                        "department",
                        "General"
                    )
                    .strip()
                )

                password = request.form.get(
                    "password",
                    ""
                )

                if not name or not class_name or not department:

                    flash(
                        "Name, class and department are required.",
                        "error"
                    )

                else:

                    if password:

                        execute(
                            """
                            UPDATE students
                            SET
                                name=%s,
                                class_name=%s,
                                department=%s,
                                password_hash=%s
                            WHERE id=%s
                            """,
                            (
                                name,
                                class_name,
                                department,
                                generate_password_hash(
                                    password
                                ),
                                student_id
                            )
                        )

                    else:

                        execute(
                            """
                            UPDATE students
                            SET
                                name=%s,
                                class_name=%s,
                                department=%s
                            WHERE id=%s
                            """,
                            (
                                name,
                                class_name,
                                department,
                                student_id
                            )
                        )

                    flash(
                        "Student profile updated. Existing results remain attached to this student.",
                        "success"
                    )

        elif action == "delete":

            student_name = (
                request.form
                .get(
                    "delete_name",
                    ""
                )
                .strip()
            )

            student = fetch_one(
                """
                SELECT *
                FROM students
                WHERE LOWER(name)=LOWER(%s)
                LIMIT 1
                """,
                (student_name,)
            )

            if not student:

                flash(
                    "No registered student was found with that name.",
                    "error"
                )

            else:

                result_files = fetch_all(
                    """
                    SELECT storage_path
                    FROM results
                    WHERE student_id=%s
                    """,
                    (student["id"],)
                )

                for result in result_files:

                    delete_storage(
                        result["storage_path"]
                    )

                execute(
                    """
                    DELETE FROM students
                    WHERE id=%s
                    """,
                    (student["id"],)
                )

                flash(
                    f"Student '{student['name']}' and all of that student's results were deleted.",
                    "success"
                )

    edit_id = request.args.get(
        "edit"
    )

    if edit_id:

        edit_student = fetch_one(
            """
            SELECT
                id,
                name,
                class_name,
                department
            FROM students
            WHERE id=%s
            """,
            (edit_id,)
        )

    return render_template(
        "admin_students.html",
        edit_student=edit_student,
        searched=searched,
        searched_student=searched_student
    )


@app.route(
    "/admin/teachers",
    methods=["GET", "POST"]
)
@login_required("admin")
def admin_teachers():

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "register":

            name = (
                request.form
                .get("name", "")
                .strip()
            )

            password = request.form.get(
                "password",
                ""
            )

            if not name or not password:

                flash(
                    "Teacher name and password are required.",
                    "error"
                )

            elif fetch_one(
                """
                SELECT id
                FROM teachers
                WHERE LOWER(name)=LOWER(%s)
                """,
                (name,)
            ):

                flash(
                    "A teacher with that name is already registered.",
                    "error"
                )

            else:

                execute(
                    """
                    INSERT INTO teachers
                    (
                        name,
                        password_hash
                    )
                    VALUES (%s,%s)
                    """,
                    (
                        name,
                        generate_password_hash(
                            password
                        )
                    )
                )

                flash(
                    "Teacher registered successfully.",
                    "success"
                )

        elif action == "delete":

            teacher_id = request.form.get(
                "teacher_id"
            )

            execute(
                """
                DELETE FROM teachers
                WHERE id=%s
                """,
                (teacher_id,)
            )

            flash(
                "Teacher deleted.",
                "success"
            )

    teachers = fetch_all(
        """
        SELECT id,name,created_at
        FROM teachers
        ORDER BY name
        """
    )

    return render_template(
        "admin_teachers.html",
        teachers=teachers
    )


@app.route(
    "/admin/subjects",
    methods=["GET", "POST"]
)
@login_required("admin")
def admin_subjects():

    if request.method == "POST":

        action = request.form.get(
            "action"
        )

        if action == "add":

            name = (
                request.form
                .get("name", "")
                .strip()
            )

            class_name = (
                request.form
                .get(
                    "class_name",
                    ""
                )
                .strip()
            )

            department = (
                request.form
                .get(
                    "department",
                    "General"
                )
                .strip()
            )

            term = (
                request.form
                .get(
                    "term",
                    "First Term"
                )
                .strip()
            )

            note = request.files.get(
                "note"
            )

            if (
                not name
                or not class_name
                or not department
                or not term
            ):

                flash(
                    "Fill the subject fields.",
                    "error"
                )

            else:

                note_path = None
                note_filename = None

                try:

                    if (
                        note
                        and
                        note.filename
                    ):

                        (
                            note_path,
                            note_filename,
                            _
                        ) = upload_to_storage(
                            note,
                            "enotes"
                        )

                    execute(
                        """
                        INSERT INTO subjects
                        (
                            name,
                            class_name,
                            department,
                            term,
                            note_path,
                            note_filename
                        )
                        VALUES
                        (%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            name,
                            class_name,
                            department,
                            term,
                            note_path,
                            note_filename
                        )
                    )

                    flash(
                        "Subject added successfully.",
                        "success"
                    )

                except Exception as exc:

                    if note_path:
                        delete_storage(
                            note_path
                        )

                    flash(
                        f"Could not add subject: {exc}",
                        "error"
                    )

        elif action == "delete":

            subject_id = request.form.get(
                "subject_id"
            )

            subject = fetch_one(
                """
                SELECT *
                FROM subjects
                WHERE id=%s
                """,
                (subject_id,)
            )

            if subject:

                if subject["note_path"]:

                    delete_storage(
                        subject["note_path"]
                    )

                execute(
                    """
                    DELETE FROM subjects
                    WHERE id=%s
                    """,
                    (subject_id,)
                )

                flash(
                    "Subject deleted.",
                    "success"
                )

    subjects = fetch_all(
        """
        SELECT *
        FROM subjects
        ORDER BY
            class_name,
            department,
            term,
            name
        """
    )

    return render_template(
        "admin_subjects.html",
        subjects=subjects
    )


@app.route(
    "/admin/results",
    methods=["GET", "POST"]
)
@login_required("admin")
def admin_results():

    if request.method == "POST":

        student_name = (
            request.form
            .get(
                "student_name",
                ""
            )
            .strip()
        )

        term = (
            request.form
            .get(
                "term",
                "First Term"
            )
            .strip()
        )

        result_file = request.files.get(
            "result_file"
        )

        student = fetch_one(
            """
            SELECT *
            FROM students
            WHERE LOWER(name)=LOWER(%s)
            LIMIT 1
            """,
            (student_name,)
        )

        if not student:

            flash(
                "Registered student not found.",
                "error"
            )

        elif (
            not result_file
            or
            not result_file.filename
        ):

            flash(
                "Choose a result file.",
                "error"
            )

        else:

            result_path = None

            try:

                (
                    result_path,
                    filename,
                    mime_type
                ) = upload_to_storage(
                    result_file,
                    f"results/student_{student['id']}"
                )

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
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (
                        student["id"],
                        term,
                        filename,
                        result_path,
                        mime_type
                    )
                )

                flash(
                    "Result uploaded successfully.",
                    "success"
                )

            except Exception as exc:

                if result_path:
                    delete_storage(
                        result_path
                    )

                flash(
                    f"Result upload failed: {exc}",
                    "error"
                )

    results = fetch_all(
        """
        SELECT
            r.*,
            s.name AS student_name
        FROM results r
        JOIN students s
            ON s.id=r.student_id
        ORDER BY r.created_at DESC
        """
    )

    return render_template(
        "admin_results.html",
        results=results
    )


@app.route(
    "/admin/news",
    methods=["GET", "POST"]
)
@login_required("admin")
def admin_news():

    if request.method == "POST":

        title = (
            request.form
            .get("title", "")
            .strip()
        )

        body = (
            request.form
            .get("body", "")
            .strip()
        )

        if not title or not body:

            flash(
                "News title and body are required.",
                "error"
            )

        else:

            execute(
                """
                INSERT INTO news
                (
                    title,
                    body
                )
                VALUES (%s,%s)
                """,
                (
                    title,
                    body
                )
            )

            flash(
                "School news published.",
                "success"
            )

    news = fetch_all(
        """
        SELECT *
        FROM news
        ORDER BY created_at DESC
        """
    )

    return render_template(
        "admin_news.html",
        news=news
    )


def get_file_item(
    kind,
    file_id
):

    if kind == "result":

        return fetch_one(
            """
            SELECT
                r.*,
                s.name AS student_name
            FROM results r
            JOIN students s
                ON s.id=r.student_id
            WHERE r.id=%s
            """,
            (file_id,)
        )

    if kind == "note":

        return fetch_one(
            """
            SELECT *
            FROM subjects
            WHERE id=%s
            """,
            (file_id,)
        )

    abort(404)


@app.route(
    "/file/<kind>/<int:file_id>"
)
def open_file(
    kind,
    file_id
):

    if kind == "result":

        if session.get("role") not in (
            "student",
            "admin"
        ):

            abort(403)

        item = get_file_item(
            kind,
            file_id
        )

        if not item:
            abort(404)

        if session.get("role") == "student":

            if (
                item["student_id"]
                !=
                session.get("user_id")
            ):

                abort(403)

        filename = item["filename"]

        extension = Path(
            filename
        ).suffix.lower()

        browser_native = {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".txt",
            ".html",
            ".htm",
            ".svg"
        }

        if extension in browser_native:

            url = signed_storage_url(
                item["storage_path"],
                1800
            )

            if not url:

                flash(
                    "Could not create a secure file link.",
                    "error"
                )

                return redirect(
                    url_for(
                        "student_results"
                    )
                )

            return render_template(
                "file_viewer.html",
                title=filename,
                external_url=url,
                is_pdf=(
                    extension == ".pdf"
                ),
                is_table=False,
                file_id=file_id,
                kind="result"
            )

        data = (
            supabase
            .storage
            .from_(SUPABASE_BUCKET)
            .download(
                item["storage_path"]
            )
        )

        try:

            if extension in (
                ".xlsx",
                ".xlsm"
            ):

                sheets = pd.read_excel(
                    io.BytesIO(data),
                    sheet_name=None
                )

            elif extension == ".xls":

                sheets = pd.read_excel(
                    io.BytesIO(data),
                    sheet_name=None
                )

            elif extension == ".ods":

                sheets = pd.read_excel(
                    io.BytesIO(data),
                    sheet_name=None,
                    engine="odf"
                )

            elif extension == ".csv":

                sheets = {
                    "Sheet 1":
                    pd.read_csv(
                        io.BytesIO(data)
                    )
                }

            else:

                url = signed_storage_url(
                    item["storage_path"],
                    1800
                )

                return render_template(
                    "file_viewer.html",
                    title=filename,
                    external_url=url,
                    is_pdf=False,
                    is_table=False,
                    file_id=file_id,
                    kind="result"
                )

            tables = []

            for sheet_name, frame in sheets.items():

                frame = frame.fillna("")

                html_table = frame.to_html(
                    index=False,
                    classes="result-table",
                    border=0
                )

                tables.append(
                    (
                        sheet_name,
                        html_table
                    )
                )

            return render_template(
                "file_viewer.html",
                title=filename,
                tables=tables,
                is_pdf=False,
                is_table=True,
                file_id=file_id,
                kind="result"
            )

        except Exception as exc:

            flash(
                f"Could not preview this spreadsheet: {exc}",
                "error"
            )

            return redirect(
                url_for(
                    "student_results"
                )
            )

    if kind == "note":

        if session.get("role") not in (
            "student",
            "teacher",
            "admin"
        ):

            abort(403)

        item = get_file_item(
            kind,
            file_id
        )

        if not item:
            abort(404)

        if not item["note_path"]:
            abort(404)

        filename = (
            item["note_filename"]
            or
            item["name"]
        )

        extension = Path(
            filename
        ).suffix.lower()

        url = signed_storage_url(
            item["note_path"],
            1800
        )

        if not url:

            flash(
                "Could not create a secure file link.",
                "error"
            )

            return redirect(
                url_for(
                    "teacher_dashboard"
                )
            )

        return render_template(
            "file_viewer.html",
            title=filename,
            external_url=url,
            is_pdf=(
                extension == ".pdf"
            ),
            is_table=False,
            file_id=file_id,
            kind="note"
        )

    abort(404)


@app.route(
    "/file/<kind>/<int:file_id>/download"
)
def download_file(
    kind,
    file_id
):

    if kind == "result":

        if session.get("role") not in (
            "student",
            "admin"
        ):

            abort(403)

        item = get_file_item(
            kind,
            file_id
        )

        if not item:
            abort(404)

        if session.get("role") == "student":

            if (
                item["student_id"]
                !=
                session.get("user_id")
            ):

                abort(403)

        path = item[
            "storage_path"
        ]

        filename = item[
            "filename"
        ]

        mime_type = item.get(
            "mime_type"
        )

    elif kind == "note":

        if session.get("role") not in (
            "student",
            "teacher",
            "admin"
        ):

            abort(403)

        item = get_file_item(
            kind,
            file_id
        )

        if not item:
            abort(404)

        path = item[
            "note_path"
        ]

        filename = (
            item["note_filename"]
            or
            item["name"]
        )

        mime_type = None

    else:

        abort(404)

    if not path:
        abort(404)

    data = (
        supabase
        .storage
        .from_(SUPABASE_BUCKET)
        .download(path)
    )

    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype=mime_type
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
        debug=True
    )
