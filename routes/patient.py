from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from db import get_db
import services
from services import role_required, APPT_SELECT, available_slots

bp = Blueprint("patient", __name__, url_prefix="/patient")


def _own_appt(appt_id):
    a = get_db().execute("SELECT * FROM appointments WHERE id=? AND patient_id=?", (appt_id, g.profile["id"])).fetchone()
    return a or abort(404)


@bp.route("/")
@role_required("patient")
def dashboard():
    db = get_db()
    depts = db.execute(
        """SELECT dep.*, COUNT(d.id) AS doctors_registered FROM departments dep
           LEFT JOIN doctors d ON d.department_id=dep.id GROUP BY dep.id ORDER BY dep.name""").fetchall()
    upcoming = db.execute(
        APPT_SELECT + " WHERE a.patient_id=? AND a.status='Booked' AND a.date>=? ORDER BY a.date, a.time",
        (g.profile["id"], date.today().isoformat())).fetchall()
    return render_template("patient/dashboard.html", depts=depts, upcoming=upcoming)


@bp.route("/doctors")
@role_required("patient")
def doctors():
    db = get_db()
    q = request.args.get("q", "").strip()
    dept = request.args.get("dept", "")
    day = request.args.get("date", "")
    like = f"%{q}%"
    sql = """SELECT d.*, dep.name AS dept FROM doctors d JOIN users u ON u.id=d.user_id
             LEFT JOIN departments dep ON dep.id=d.department_id
             WHERE u.is_active=1 AND (d.name LIKE ? OR dep.name LIKE ?)"""
    params = [like, like]
    if dept.isdigit():
        sql += " AND d.department_id=?"
        params.append(int(dept))
    rows = db.execute(sql + " ORDER BY d.name", params).fetchall()
    result = []
    for r in rows:
        slots = available_slots(db, r["id"])
        n = sum(len(v) for v in slots.values()) if not day else len(slots.get(day, []))
        if day and n == 0:
            continue
        result.append((r, n))
    depts = db.execute("SELECT * FROM departments ORDER BY name").fetchall()
    return render_template("patient/doctors.html", doctors=result, depts=depts, q=q, dept=dept,
                           day=day, days=services.next_days())


@bp.route("/doctors/<int:doctor_id>")
@role_required("patient")
def doctor_profile(doctor_id):
    db = get_db()
    doc = db.execute(
        """SELECT d.*, dep.name AS dept FROM doctors d JOIN users u ON u.id=d.user_id
           LEFT JOIN departments dep ON dep.id=d.department_id WHERE d.id=? AND u.is_active=1""",
        (doctor_id,)).fetchone() or abort(404)
    return render_template("patient/doctor_profile.html", doc=doc, slots=available_slots(db, doctor_id))


@bp.route("/book", methods=["POST"])
@role_required("patient")
def book():
    f = request.form
    doctor_id = f.get("doctor_id", type=int)
    ok, msg = services.book(get_db(), g.profile["id"], doctor_id, f.get("date", ""), f.get("slot", ""), f.get("reason", ""))
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("patient.dashboard") if ok else url_for("patient.doctor_profile", doctor_id=doctor_id))


@bp.route("/appointments/<int:appt_id>/cancel", methods=["POST"])
@role_required("patient")
def cancel(appt_id):
    _own_appt(appt_id)
    db = get_db()
    db.execute("UPDATE appointments SET status='Cancelled' WHERE id=? AND status='Booked'", (appt_id,))
    db.commit()
    flash("Appointment cancelled.", "info")
    return redirect(url_for("patient.dashboard"))


@bp.route("/appointments/<int:appt_id>/reschedule", methods=["GET", "POST"])
@role_required("patient")
def reschedule(appt_id):
    a = _own_appt(appt_id)
    db = get_db()
    if a["status"] != "Booked":
        flash("Only booked appointments can be rescheduled.", "warning")
        return redirect(url_for("patient.dashboard"))
    if request.method == "POST":
        ok, msg = services.reschedule(db, a, request.form.get("date", ""), request.form.get("slot", ""))
        flash(msg, "success" if ok else "danger")
        if ok:
            return redirect(url_for("patient.dashboard"))
    doc = db.execute("SELECT * FROM doctors WHERE id=?", (a["doctor_id"],)).fetchone()
    return render_template("patient/reschedule.html", a=a, doc=doc, slots=available_slots(db, a["doctor_id"]))


@bp.route("/history")
@role_required("patient")
def history():
    rows = get_db().execute(APPT_SELECT + " WHERE a.patient_id=? ORDER BY a.date DESC, a.time DESC",
                            (g.profile["id"],)).fetchall()
    return render_template("patient/history.html", appts=rows)


@bp.route("/profile", methods=["GET", "POST"])
@role_required("patient")
def profile():
    if request.method == "POST":
        f = request.form
        age = f.get("age", "")
        if not f.get("name", "").strip() or (age and (not age.isdigit() or not 0 < int(age) < 130)):
            flash("Name is required and age must be a valid number.", "danger")
        else:
            db = get_db()
            db.execute("UPDATE patients SET name=?, age=?, gender=?, phone=?, address=? WHERE id=?",
                       (f["name"].strip(), int(age) if age else None, f.get("gender", ""),
                        f.get("phone", "").strip(), f.get("address", "").strip(), g.profile["id"]))
            db.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("patient.profile"))
    return render_template("patient/profile.html", p=g.profile)
