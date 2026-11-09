from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3
from db import get_db

bp = Blueprint("auth", __name__)
HOME = {"admin": "admin.dashboard", "doctor": "doctor.dashboard", "patient": "patient.dashboard"}


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for(HOME[g.user["role"]]))
    return render_template("home.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "danger")
        elif not user["is_active"]:
            flash("This account has been blacklisted. Contact the hospital admin.", "danger")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for(HOME[user["role"]]))
    return render_template("login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        username, password = f.get("username", "").strip(), f.get("password", "")
        name = f.get("name", "").strip()
        errors = []
        if len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if not name:
            errors.append("Name is required.")
        age = f.get("age", "")
        if age and (not age.isdigit() or not 0 < int(age) < 130):
            errors.append("Enter a valid age.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register.html", form=f)
        db = get_db()
        try:
            cur = db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?, 'patient')",
                (username, generate_password_hash(password)),
            )
            db.execute(
                "INSERT INTO patients (user_id, name, age, gender, phone, address) VALUES (?,?,?,?,?,?)",
                (cur.lastrowid, name, int(age) if age else None, f.get("gender", ""),
                 f.get("phone", "").strip(), f.get("address", "").strip()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash("That username is already taken.", "danger")
            return render_template("register.html", form=f)
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("register.html", form={})


@bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("auth.login"))
