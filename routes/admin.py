import sqlite3
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from werkzeug.security import generate_password_hash
from db import get_db
from services import role_required, APPT_SELECT

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@role_required("admin")
def dashboard():
    db = get_db()
    counts = {
        "doctors": db.execute("SELECT COUNT(*) FROM doctors").fetchone()[0],
        "patients": db.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
        "appointments": db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
    }
    status = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) n FROM appointments GROUP BY status")}
    by_dept = db.execute(
        """SELECT dep.name, COUNT(a.id) n FROM departments dep
           LEFT JOIN doctors d ON d.department_id=dep.id
           LEFT JOIN appointments a ON a.doctor_id=d.id GROUP BY dep.id ORDER BY dep.name"""
    ).fetchall()
    upcoming = db.execute(
        APPT_SELECT + " WHERE a.status='Booked' AND a.date>=? ORDER BY a.date, a.time LIMIT 5",
        (date.today().isoformat(),),
    ).fetchall()
    return render_template("admin/dashboard.html", counts=counts, status=status,
                           by_dept=[(r["name"], r["n"]) for r in by_dept], upcoming=upcoming)


# ---------- Doctors ----------
@bp.route("/doctors")
@role_required("admin")
def doctors():
    q = request.args.get("q", "").strip()
    like = f"%{q}%"
    rows = get_db().execute(
        """SELECT d.*, dep.name AS dept, u.username, u.is_active FROM doctors d
           JOIN users u ON u.id=d.user_id LEFT JOIN departments dep ON dep.id=d.department_id
           WHERE d.name LIKE ? OR dep.name LIKE ? ORDER BY d.name""",
        (like, like),
    ).fetchall()
    return render_template("admin/doctors.html", doctors=rows, q=q)


@bp.route("/doctors/new", methods=["GET", "POST"])
@bp.route("/doctors/<int:doctor_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def doctor_form(doctor_id=None):
    db = get_db()
    doc = None
    if doctor_id:
        doc = db.execute(
            "SELECT d.*, u.username FROM doctors d JOIN users u ON u.id=d.user_id WHERE d.id=?", (doctor_id,)
        ).fetchone() or abort(404)
    depts = db.execute("SELECT * FROM departments ORDER BY name").fetchall()
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        exp = f.get("experience", "0") or "0"
        if not name or not exp.isdigit():
            flash("Name is required and experience must be a number.", "danger")
            return render_template("admin/doctor_form.html", doc=f, depts=depts, editing=bool(doctor_id))
        dept = f.get("department_id") or None
        try:
            if doc:
                if f.get("password") and len(f["password"]) < 6:
                    raise ValueError("Password must be at least 6 characters.")
                db.execute(
                    "UPDATE doctors SET name=?, department_id=?, experience=?, qualification=?, bio=?, phone=? WHERE id=?",
                    (name, dept, int(exp), f.get("qualification", ""), f.get("bio", ""), f.get("phone", ""), doctor_id),
                )
                if f.get("password"):
                    db.execute("UPDATE users SET password_hash=? WHERE id=?",
                               (generate_password_hash(f["password"]), doc["user_id"]))
                flash("Doctor updated.", "success")
            else:
                username, pw = f.get("username", "").strip(), f.get("password", "")
                if len(username) < 3 or len(pw) < 6:
                    raise ValueError("Username (min 3) and password (min 6) are required.")
                cur = db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?, 'doctor')",
                                 (username, generate_password_hash(pw)))
                db.execute(
                    "INSERT INTO doctors (user_id, name, department_id, experience, qualification, bio, phone) VALUES (?,?,?,?,?,?,?)",
                    (cur.lastrowid, name, dept, int(exp), f.get("qualification", ""), f.get("bio", ""), f.get("phone", "")),
                )
                flash("Doctor added.", "success")
            db.commit()
            return redirect(url_for("admin.doctors"))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("That username already exists.", "danger")
        except ValueError as e:
            db.rollback()
            flash(str(e), "danger")
        return render_template("admin/doctor_form.html", doc=f, depts=depts, editing=bool(doctor_id))
    return render_template("admin/doctor_form.html", doc=doc, depts=depts, editing=bool(doctor_id))


@bp.route("/doctors/<int:doctor_id>/delete", methods=["POST"])
@role_required("admin")
def doctor_delete(doctor_id):
    db = get_db()
    row = db.execute("SELECT user_id FROM doctors WHERE id=?", (doctor_id,)).fetchone() or abort(404)
    db.execute("DELETE FROM users WHERE id=?", (row["user_id"],))  # cascades to doctor, availability, appointments
    db.commit()
    flash("Doctor removed.", "success")
    return redirect(url_for("admin.doctors"))


def _toggle(user_id):
    db = get_db()
    db.execute("UPDATE users SET is_active = 1 - is_active WHERE id=? AND role!='admin'", (user_id,))
    if db.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()["is_active"] == 0:
        # blacklisting cancels future booked appointments
        db.execute(
            """UPDATE appointments SET status='Cancelled' WHERE status='Booked' AND date>=? AND
               (doctor_id IN (SELECT id FROM doctors WHERE user_id=?) OR
                patient_id IN (SELECT id FROM patients WHERE user_id=?))""",
            (date.today().isoformat(), user_id, user_id),
        )
    db.commit()


@bp.route("/doctors/<int:doctor_id>/blacklist", methods=["POST"])
@role_required("admin")
def doctor_blacklist(doctor_id):
    row = get_db().execute("SELECT user_id FROM doctors WHERE id=?", (doctor_id,)).fetchone() or abort(404)
    _toggle(row["user_id"])
    flash("Doctor status updated.", "success")
    return redirect(request.referrer or url_for("admin.doctors"))


# ---------- Departments ----------
@bp.route("/departments", methods=["GET", "POST"])
@role_required("admin")
def departments():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Department name is required.", "danger")
        else:
            try:
                db.execute("INSERT INTO departments (name, description) VALUES (?,?)",
                           (name, request.form.get("description", "").strip()))
                db.commit()
                flash("Department added.", "success")
            except sqlite3.IntegrityError:
                flash("Department already exists.", "danger")
        return redirect(url_for("admin.departments"))
    rows = db.execute(
        "SELECT dep.*, COUNT(d.id) AS doctors_registered FROM departments dep "
        "LEFT JOIN doctors d ON d.department_id=dep.id GROUP BY dep.id ORDER BY dep.name"
    ).fetchall()
    return render_template("admin/departments.html", departments=rows)


# ---------- Patients ----------
@bp.route("/patients")
@role_required("admin")
def patients():
    q = request.args.get("q", "").strip()
    like = f"%{q}%"
    rows = get_db().execute(
        """SELECT p.*, u.username, u.is_active FROM patients p JOIN users u ON u.id=p.user_id
           WHERE p.name LIKE ? OR CAST(p.id AS TEXT)=? OR p.phone LIKE ? ORDER BY p.name""",
        (like, q, like),
    ).fetchall()
    return render_template("admin/patients.html", patients=rows, q=q)


@bp.route("/patients/<int:patient_id>")
@role_required("admin")
def patient_detail(patient_id):
    db = get_db()
    p = db.execute("SELECT p.*, u.username, u.is_active FROM patients p JOIN users u ON u.id=p.user_id WHERE p.id=?",
                   (patient_id,)).fetchone() or abort(404)
    appts = db.execute(APPT_SELECT + " WHERE a.patient_id=? ORDER BY a.date DESC, a.time DESC", (patient_id,)).fetchall()
    return render_template("admin/patient_detail.html", p=p, appts=appts)


@bp.route("/patients/<int:patient_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def patient_edit(patient_id):
    db = get_db()
    p = db.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone() or abort(404)
    if request.method == "POST":
        f = request.form
        age = f.get("age", "")
        if not f.get("name", "").strip() or (age and not age.isdigit()):
            flash("Name is required and age must be a number.", "danger")
        else:
            db.execute("UPDATE patients SET name=?, age=?, gender=?, phone=?, address=? WHERE id=?",
                       (f["name"].strip(), int(age) if age else None, f.get("gender", ""),
                        f.get("phone", ""), f.get("address", ""), patient_id))
            db.commit()
            flash("Patient updated.", "success")
            return redirect(url_for("admin.patient_detail", patient_id=patient_id))
    return render_template("admin/patient_form.html", p=p)


@bp.route("/patients/<int:patient_id>/blacklist", methods=["POST"])
@role_required("admin")
def patient_blacklist(patient_id):
    row = get_db().execute("SELECT user_id FROM patients WHERE id=?", (patient_id,)).fetchone() or abort(404)
    _toggle(row["user_id"])
    flash("Patient status updated.", "success")
    return redirect(request.referrer or url_for("admin.patients"))


@bp.route("/patients/<int:patient_id>/delete", methods=["POST"])
@role_required("admin")
def patient_delete(patient_id):
    db = get_db()
    row = db.execute("SELECT user_id FROM patients WHERE id=?", (patient_id,)).fetchone() or abort(404)
    db.execute("DELETE FROM users WHERE id=?", (row["user_id"],))
    db.commit()
    flash("Patient removed.", "success")
    return redirect(url_for("admin.patients"))


# ---------- Appointments ----------
@bp.route("/appointments")
@role_required("admin")
def appointments():
    when = request.args.get("when", "all")
    today = date.today().isoformat()
    sql = APPT_SELECT
    params = ()
    if when == "upcoming":
        sql += " WHERE a.status='Booked' AND a.date>=? ORDER BY a.date, a.time"
        params = (today,)
    elif when == "past":
        sql += " WHERE a.status!='Booked' OR a.date<? ORDER BY a.date DESC, a.time DESC"
        params = (today,)
    else:
        sql += " ORDER BY a.date DESC, a.time DESC"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("admin/appointments.html", appts=rows, when=when)


@bp.route("/appointments/<int:appt_id>/cancel", methods=["POST"])
@role_required("admin")
def appointment_cancel(appt_id):
    db = get_db()
    db.execute("UPDATE appointments SET status='Cancelled' WHERE id=? AND status='Booked'", (appt_id,))
    db.commit()
    flash("Appointment cancelled.", "success")
    return redirect(request.referrer or url_for("admin.appointments"))
