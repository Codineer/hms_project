from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from db import get_db
from services import role_required, APPT_SELECT, SLOTS, next_days

bp = Blueprint("doctor", __name__, url_prefix="/doctor")


def _own_appt(appt_id):
    a = get_db().execute(APPT_SELECT + " WHERE a.id=? AND a.doctor_id=?", (appt_id, g.profile["id"])).fetchone()
    return a or abort(404)


@bp.route("/")
@role_required("doctor")
def dashboard():
    db = get_db()
    me = g.profile["id"]
    today = date.today()
    week_end = (today + timedelta(days=6)).isoformat()
    todays = db.execute(APPT_SELECT + " WHERE a.doctor_id=? AND a.date=? AND a.status='Booked' ORDER BY a.time",
                        (me, today.isoformat())).fetchall()
    week = db.execute(
        APPT_SELECT + " WHERE a.doctor_id=? AND a.date BETWEEN ? AND ? AND a.status='Booked' ORDER BY a.date, a.time",
        (me, today.isoformat(), week_end)).fetchall()
    patients = db.execute(
        """SELECT p.id, p.name, p.age, p.gender, p.phone, COUNT(a.id) AS visits
           FROM patients p JOIN appointments a ON a.patient_id=p.id
           WHERE a.doctor_id=? GROUP BY p.id ORDER BY p.name""", (me,)).fetchall()
    return render_template("doctor/dashboard.html", todays=todays, week=week, patients=patients)


@bp.route("/appointments/<int:appt_id>/complete", methods=["GET", "POST"])
@role_required("doctor")
def complete(appt_id):
    a = _own_appt(appt_id)
    if a["status"] == "Cancelled":
        flash("Cancelled appointments cannot be completed.", "warning")
        return redirect(url_for("doctor.dashboard"))
    if request.method == "POST":
        f = request.form
        if not f.get("diagnosis", "").strip():
            flash("Diagnosis is required.", "danger")
        else:
            db = get_db()
            db.execute(
                """INSERT INTO treatments (appointment_id, diagnosis, prescription, notes) VALUES (?,?,?,?)
                   ON CONFLICT(appointment_id) DO UPDATE SET diagnosis=excluded.diagnosis,
                   prescription=excluded.prescription, notes=excluded.notes""",
                (appt_id, f["diagnosis"].strip(), f.get("prescription", "").strip(), f.get("notes", "").strip()))
            db.execute("UPDATE appointments SET status='Completed' WHERE id=?", (appt_id,))
            db.commit()
            flash("Visit marked as completed and treatment saved.", "success")
            return redirect(url_for("doctor.dashboard"))
    return render_template("doctor/complete.html", a=a)


@bp.route("/appointments/<int:appt_id>/cancel", methods=["POST"])
@role_required("doctor")
def cancel(appt_id):
    _own_appt(appt_id)
    db = get_db()
    db.execute("UPDATE appointments SET status='Cancelled' WHERE id=? AND status='Booked'", (appt_id,))
    db.commit()
    flash("Appointment cancelled.", "info")
    return redirect(url_for("doctor.dashboard"))


@bp.route("/availability", methods=["GET", "POST"])
@role_required("doctor")
def availability():
    db = get_db()
    me = g.profile["id"]
    days = next_days()
    if request.method == "POST":
        chosen = set(request.form.getlist("slots"))  # values "YYYY-MM-DD|HH:MM"
        booked = {f"{r['date']}|{r['time']}" for r in db.execute(
            "SELECT date, time FROM appointments WHERE doctor_id=? AND status IN ('Booked','Completed')", (me,))}
        valid = {f"{d}|{s}" for d in days for s in SLOTS}
        final = (chosen & valid) | (booked & valid)  # never drop a slot that has a patient
        db.execute("DELETE FROM availability WHERE doctor_id=? AND date BETWEEN ? AND ?", (me, days[0], days[-1]))
        for item in final:
            d, s = item.split("|")
            db.execute("INSERT INTO availability (doctor_id, date, slot) VALUES (?,?,?)", (me, d, s))
        db.commit()
        flash("Availability updated for the next 7 days.", "success")
        return redirect(url_for("doctor.availability"))
    current = {f"{r['date']}|{r['slot']}" for r in db.execute(
        "SELECT date, slot FROM availability WHERE doctor_id=?", (me,))}
    return render_template("doctor/availability.html", days=days, slots=SLOTS, current=current)


@bp.route("/patients/<int:patient_id>")
@role_required("doctor")
def patient_history(patient_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM appointments WHERE doctor_id=? AND patient_id=?", (g.profile["id"], patient_id)).fetchone():
        abort(404)
    p = db.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    history = db.execute(
        APPT_SELECT + " WHERE a.patient_id=? AND a.status='Completed' ORDER BY a.date DESC, a.time DESC", (patient_id,)).fetchall()
    return render_template("doctor/patient_history.html", p=p, history=history)
