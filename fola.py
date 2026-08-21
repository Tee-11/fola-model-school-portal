from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_from_directory,
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename

from data import ADMINS, SUBJECTS

import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

app.secret_key = "CHANGE_THIS_SECRET_KEY"


DATABASE = "school.db"

RESULT_FOLDER = "results"

app.config["RESULT_FOLDER"] = RESULT_FOLDER



os.makedirs(
    RESULT_FOLDER,
    exist_ok=True
)


def get_db():

    db = sqlite3.connect(
        DATABASE
    )

    db.row_factory = sqlite3.Row

    return db



def create_database():

    db = get_db()

    cursor = db.cursor()



    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            class_name TEXT NOT NULL,

            department TEXT NOT NULL,

            password TEXT NOT NULL

        )
    """)



    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            title TEXT NOT NULL,

            content TEXT NOT NULL,

            date TEXT NOT NULL,

            admin TEXT NOT NULL

        )
    """)


    db.commit()

    db.close()


create_database()



def is_admin():

    return "admin" in session


def is_student():

    return "student_id" in session



def find_student(name):

    db = get_db()


    student = db.execute(
        """
        SELECT *
        FROM students
        WHERE LOWER(name) = LOWER(?)
        """,

        (name.strip(),)

    ).fetchone()


    db.close()


    return student



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
        )


        if not name or not password:

            flash(
                "Please enter your name and password."
            )

            return redirect(
                url_for("login")
            )



        for admin_name, admin_password in ADMINS.items():


            if name.lower() == admin_name.lower():


                if password == admin_password:


                    session.clear()


                    session["admin"] = admin_name


                    return redirect(
                        url_for(
                            "admin_dashboard"
                        )
                    )


                flash(
                    "Incorrect admin password."
                )


                return redirect(
                    url_for("login")
                )



        student = find_student(name)


        if student is None:

            flash(
                "Student account not found."
            )

            return redirect(
                url_for("login")
            )


        if not check_password_hash(
            student["password"],
            password
        ):

            flash(
                "Incorrect student password."
            )

            return redirect(
                url_for("login")
            )



        session.clear()


        session["student_id"] = (
            student["id"]
        )


        session["student_name"] = (
            student["name"]
        )


        session["student_class"] = (
            student["class_name"]
        )


        session["student_department"] = (
            student["department"]
        )


        return redirect(
            url_for("dashboard")
        )


    return render_template(
        "login.html"
    )



@app.route("/dashboard")
def dashboard():


    if not is_student():

        return redirect(
            url_for("login")
        )


    return render_template(

        "dashboard.html",

        student=session["student_name"],

        student_class=session["student_class"],

        student_department=session[
            "student_department"
        ]

    )



@app.route("/subjects")
def subjects():


    if not is_student():

        return redirect(
            url_for("login")
        )


    student_class = (
        session["student_class"]
    )


    student_department = (
        session["student_department"]
    )



    class_data = SUBJECTS.get(
        student_class,
        {}
    )



    class_subjects = class_data.get(
        student_department,
        {}
    )


    return render_template(

        "subjects.html",

        student=session["student_name"],

        student_class=student_class,

        student_department=student_department,

        subjects=class_subjects

    )



@app.route("/results")
def results():


    if not is_student():

        return redirect(
            url_for("login")
        )


    student_id = (
        session["student_id"]
    )


    folder = os.path.join(

        RESULT_FOLDER,

        str(student_id)

    )


    if os.path.exists(folder):

        result_files = os.listdir(
            folder
        )

    else:

        result_files = []


    return render_template(

        "results.html",

        student=session["student_name"],

        results=result_files

    )



@app.route("/result/<int:student_id>/<filename>")
def view_result(student_id, filename):

    # Student can only view their own result
    if is_student():

        if student_id != session["student_id"]:

            return "Access denied.", 403

    # Admin can view any student's result
    elif not is_admin():

        return redirect(url_for("login"))


    folder = os.path.join(
        RESULT_FOLDER,
        str(student_id)
    )


    # Check that the file exists
    filepath = os.path.join(
        folder,
        filename
    )


    if not os.path.exists(filepath):

        return "Result file not found.", 404


    return render_template(
        "result_viewer.html",
        student_id=student_id,
        filename=filename
    )

@app.route(
    "/result-file/<int:student_id>/<filename>"
)
def serve_result_file(
    student_id,
    filename
):

    # Student can only access their own result
    if is_student():

        if student_id != session["student_id"]:

            return "Access denied.", 403

    elif not is_admin():

        return redirect(
            url_for("login")
        )


    folder = os.path.join(
        RESULT_FOLDER,
        str(student_id)
    )


    return send_from_directory(
        folder,
        filename,
        as_attachment=False
    )




@app.route("/news")
def news():


    if not is_student():

        return redirect(
            url_for("login")
        )


    db = get_db()


    news_items = db.execute(
        """
        SELECT *
        FROM news
        ORDER BY id DESC
        """
    ).fetchall()


    db.close()


    return render_template(

        "news.html",

        news=news_items

    )



@app.route("/admin")
def admin_dashboard():


    if not is_admin():

        return redirect(
            url_for("login")
        )


    db = get_db()


    students = db.execute(
        """
        SELECT
            id,
            name,
            class_name,
            department
        FROM students
        ORDER BY name
        """
    ).fetchall()


    news_items = db.execute(
        """
        SELECT *
        FROM news
        ORDER BY id DESC
        """
    ).fetchall()


    db.close()


    return render_template(

        "admin.html",

        admin=session["admin"],

        students=students,

        news=news_items

    )



@app.route(
    "/admin/register-student",
    methods=["POST"]
)
def register_student():


    if not is_admin():

        return redirect(
            url_for("login")
        )


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
    )



    if not name:

        flash(
            "Enter the student's name."
        )

        return redirect(
            url_for("admin_dashboard")
        )


    if not class_name:

        flash(
            "Select the student's class."
        )

        return redirect(
            url_for("admin_dashboard")
        )


    if not password:

        flash(
            "Create a password for the student."
        )

        return redirect(
            url_for("admin_dashboard")
        )



    if class_name in [
        "JSS1",
        "JSS2",
        "JSS3"
    ]:

        department = "General"



    else:

        if department not in [
            "Science",
            "Art",
            "Commercial"
        ]:

            flash(
                "Select Science, Art or Commercial."
            )

            return redirect(
                url_for("admin_dashboard")
            )



    if class_name not in SUBJECTS:

        flash(
            "Invalid class selected."
        )

        return redirect(
            url_for("admin_dashboard")
        )



    if find_student(name):

        flash(
            "A student with this name already exists."
        )

        return redirect(
            url_for("admin_dashboard")
        )



    password_hash = (
        generate_password_hash(
            password
        )
    )



    db = get_db()


    db.execute(

        """
        INSERT INTO students
        (
            name,
            class_name,
            department,
            password
        )

        VALUES (?, ?, ?, ?)
        """,

        (
            name,
            class_name,
            department,
            password_hash
        )

    )


    db.commit()

    db.close()


    flash(
        f"{name} was registered successfully."
    )


    return redirect(
        url_for("admin_dashboard")
    )

@app.route("/admin/upload-result", methods=["POST"])
def upload_result():

    if not is_admin():
        return redirect(url_for("login"))

    student_name = request.form.get(
        "student_name", ""
    ).strip()

    result_file = request.files.get(
        "result_file"
    )

    if not student_name:
        flash("Please enter the student's registered name.")
        return redirect(url_for("admin_dashboard"))

    if not result_file or result_file.filename == "":
        flash("Please select a result file.")
        return redirect(url_for("admin_dashboard"))

    db = get_db()

    student = db.execute(
        """
        SELECT *
        FROM students
        WHERE LOWER(name) = LOWER(?)
        """,
        (student_name,)
    ).fetchone()

    if student is None:

        db.close()

        flash(
            "No registered student was found with that name."
        )

        return redirect(url_for("admin_dashboard"))

    student_id = student["id"]

    student_folder = os.path.join(
        RESULT_FOLDER,
        str(student_id)
    )

    os.makedirs(
        student_folder,
        exist_ok=True
    )

    filename = secure_filename(
        result_file.filename
    )

    result_file.save(
        os.path.join(
            student_folder,
            filename
        )
    )

    db.close()

    flash(
        f"Result uploaded successfully for {student['name']}."
    )

    return redirect(
        url_for("admin_dashboard")
    )



@app.route(
    "/admin/add-news",
    methods=["POST"]
)
def add_news():


    if not is_admin():

        return redirect(
            url_for("login")
        )


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
            "Enter both the news title and content."
        )

        return redirect(
            url_for("admin_dashboard")
        )


    date = datetime.now().strftime(

        "%d/%m/%Y %I:%M %p"

    )


    db = get_db()


    db.execute(

        """
        INSERT INTO news
        (
            title,
            content,
            date,
            admin
        )

        VALUES (?, ?, ?, ?)
        """,

        (
            title,
            content,
            date,
            session["admin"]
        )

    )


    db.commit()

    db.close()


    flash(
        "School news published successfully."
    )


    return redirect(
        url_for("admin_dashboard")
    )



@app.route(
    "/admin/delete-news/<int:news_id>",
    methods=["POST"]
)
def delete_news(news_id):


    if not is_admin():

        return redirect(
            url_for("login")
        )


    db = get_db()


    db.execute(

        """
        DELETE FROM news
        WHERE id = ?
        """,

        (news_id,)

    )


    db.commit()

    db.close()


    flash(
        "News deleted."
    )


    return redirect(
        url_for("admin_dashboard")
    )



@app.route(
    "/admin/delete-student/<int:student_id>",
    methods=["POST"]
)
def delete_student(student_id):


    if not is_admin():

        return redirect(
            url_for("login")
        )


    db = get_db()


    student = db.execute(

        """
        SELECT *
        FROM students
        WHERE id = ?
        """,

        (student_id,)

    ).fetchone()


    db.execute(

        """
        DELETE FROM students
        WHERE id = ?
        """,

        (student_id,)

    )


    db.commit()

    db.close()



    folder = os.path.join(

        RESULT_FOLDER,

        str(student_id)

    )


    if os.path.exists(folder):


        for filename in os.listdir(folder):


            filepath = os.path.join(

                folder,

                filename

            )


            if os.path.isfile(filepath):

                os.remove(filepath)


        os.rmdir(folder)


    flash(
        "Student deleted."
    )


    return redirect(
        url_for("admin_dashboard")
    )

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )



if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=5000,

        debug=True

    )
