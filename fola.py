from flask import Flask, render_template, request, redirect, url_for, session
from data import STUDENTS, NOTES

app= Flask(__name__)
app.secret_key= "fola_secret_key_change_me"

@app.route("/", methods= ["GET", "POST"])
def login():
    error= None
    if request.method == "POST":
        name= request.form["name"].lower().replace(" ", "")
        class_= request.form["class"].lower()
        stream= request.form["stream"].lower()
        password= request.form["password"]
        key= f"{name}_{class_}_{stream}"

        if key in STUDENTS and STUDENTS[key] == password:
            session["class"]= class_
            session["stream"]= stream
            return redirect(url_for("subjects"))
        else:
            error= "Invalid Name, Class, Stream, or Password"
    return render_template("login.html", error=error)

@app.route("/subjects")
def subjects():
    if "class" not in session:
        return redirect(url_for("login"))

    class_= session["class"]
    stream= session["stream"]

    if class_.startswith("jss"):
        stream= "general"

    subjects= NOTES.get(class_, {}).get(stream, {})
    return render_template("subjects.html", subjects=subjects, class_=class_.upper(), stream=stream.title())

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
