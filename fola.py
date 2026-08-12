from flask import (Flask, render_template, request, redirect, url_for, session, flash, send_from_directory)
from werkzeug.utils import secure_filename
from functools import wraps
import json
import os
import uuid
from data import students, subjects, admins

app= Flask(__name__)
app.secret_key= "fola_model_school_portal_2004"

RESULT_FOLDER= os.path.join("uploads", "results")

ALLOWED_EXTENSION= {"pdf", "png", "jpg", "jpeg"}
app.config["RESULT_FOLDER"]= RESULT_FOLDER

os.makedirs(RESULT_FOLDER, exist_ok= True)

NEWS_FILE= "news.json"
RESULTS_FILE= "results.json"

if not os.path.exists(NEWS_FILE):
    with open(NEWS_FILE, "w") as f:
        json.dump([], f, indent= 4)

if not os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE, "w") as f:
        json.dump({}, f, indent= 4)

def load_news():
    try:
        with open(NEWS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_news(news):
    with open(NEWS_FILE, "w") as f:
        json.dump(news, f, indent= 4)

def load_results():
    try:
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_results(results):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent= 4)

def allowed_file(filename):
    return ("." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS)

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):

        if session.get("role") not in ["admin", "student"]:
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper

def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):

        if session.get("role") != "admin":
            flash("You must be an administrator to access this page.")
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper

@app.route("/", methods= ["GET", "POST"])
def login():
    if request.method == "POST":
        name= request.form["name"].strip()
        class_= request.form["class"].strip()
        stream= request.form["stream"].strip()
        password= request.form["password"]

        if name in admins and admins[name] == password:
                session.clear()
                session["name"]= name
                session["role"]= "admin"
                session["class"]= "ADMIN"
                session["stream"]= "ADMIN"
                return redirect(url_for("admin"))

        student_key= f"{name}_{class_}_{stream}"
        if student_key in students and students[student_key] == password:
                session.clear()
                session["student_key"]= student_key
                session["name"]= name
                session["class"]= class_
                session["stream"]= stream
                session["role"]= "student"
                return redirect(url_for("dashboard"))
        else:
                flash("Incorrect student information or password")
                return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    name= session["name"]
    class_= session["class"]
    stream= session["stream"]
    role= session["role"]
    return render_template("dashboard.html")

@app.route("/subjects")
@login_required
def subject_page():
    class_= session["class"].strip()
    stream= session["stream"].strip()
    if class_. startswith("jss"):
        stream= "general"
    student_subjects= subjects.get(class_, {}).get(stream, {})
    return render_template("subjects.html", subjects= student_subjects)

@app.route("/result")
@login_required
def result():
    student_key= session.get("student_key")
    all_results= load_results()
    student_result= all_results.get(student_key)
    return render_template("result.html", result= student_result, name= session.get("name"))

@app.route("/my-result-file")
@login_required
def my_result_file():
    student_key= session.get("student_key")
    all_result= load_result()
    student_result= all_result.get(student_key)
    if not student_result:
        flash("Your result has not been uploaded yet.")
        return redirect( url_for("result") )
    filename= student_result.get("filename")
    if not filename:
        flash("Result file could not be found")
        return redirect( url_for("result") )
    return send_from_directory(app.config["RESULT_FOLDER"], filename)

@app.route("/news")
@login_required
def news():
    school_news= load_news()
    school_news.reverse()
    return render_template("news.html", news= school_news)

@app.route("/admin")
@login_required
def admin():
    if session.get("role") != "admin":
        flash("Admin access required.", "error")
        return redirect(url_for("login"))
    return render_template("admin.html", name= session.get("name"))

@app.route("/admin/add-news", methods= ["POST"])
@admin_required
def add_news():
    title= request.form.get("title", "").strip()
    content= request.form.get("content", "").strip()
    if not title or not content:
        flash("Please enter both a title and news content.")
        return redirect(url_for("admin"))
    news= load_news()
    news.append({"title": title, "content": content, "posted_by": session.get("admin_name")})
    save_news(news)
    flash("School news uploaded successfully.")
    return redirect(url_for("admin"))

@app.route("/admin/add-result", methods= ["GET", "POST"])
@login_required
def upload_result():
    if session.get("role") != "admin":
       return redirect(url_for("login"))
    name= request.form["name"].strip()
    result_file= request.files.get("result_file")
    if name not in students:
        flash("The student does not exists.")
        return redirect(url_for("admin"))
    if not result_file:
        flash("Please select a result file")
        return redirect(url_for("admin"))
    if result_file.filename == "":
        flash("Please select a result file")
        return redirect(url_for("admin"))
    if not allowed_file(result_file.filename):
        flash("Only PDF, JPG, JPEG and PNG files are allowed.")
        return redirect(url_for("admin"))
    original_name= secure_filename(result_file.filename)
    extension= original_name.rsplit(".", 1)[1].lower()
    unique_name= (
        f"{student_key}_"
        f"{uuid.uuid4().hex}."
        f"{extension}"
    )
    filepath= os.path.join(app.config["RESULT_FOLDER"], unique_name)
    result_file.save(filepath)
    results= load_results()
    old_results= results.get(student_key)
    if old_result:
        old_filename = old_result.get("filename")
    if old_filename:
        old_path= os.path.join(app.config["RESULT_FOLDER"], old_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
    results[student_key]= {
        "filename":
            unique_name,
        "original_filename":
            original_name,
        "uploaded_by":
            session.get("admin_name")
    }
    save_results(results)
    flash("Student result uploaded successfully.")
    return redirect(url_for("admin"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
