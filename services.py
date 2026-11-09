"""Shared business logic: slots, booking, rescheduling."""
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from flask import g, abort, flash, redirect, url_for

SLOTS = ["09:00", "10:00", "11:00", "12:00", "16:00", "17:00", "18:00", "19:00"]


def role_required(role):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if g.user is None:
                flash("Please log in first.", "warning")
                return redirect(url_for("auth.login"))
            if g.user["role"] != role:
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


def next_days(n=7):
    return [(date.today() + timedelta(days=i)).isoformat() for i in range(n)]


def slot_is_past(d, s):
    return datetime.strptime(f"{d} {s}", "%Y-%m-%d %H:%M") <= datetime.now()


def available_slots(db, doctor_id):
    """Return {date: [free slots]} for the next 7 days."""
    days = next_days()
    avail = db.execute(
        "SELECT date, slot FROM availability WHERE doctor_id=? AND date BETWEEN ? AND ? ORDER BY date, slot",
        (doctor_id, days[0], days[-1]),
    ).fetchall()
    taken = {
        (r["date"], r["time"])
        for r in db.execute(
            "SELECT date, time FROM appointments WHERE doctor_id=? AND status IN ('Booked','Completed')",
            (doctor_id,),
        )
    }
    out = {d: [] for d in days}
    for r in avail:
        if (r["date"], r["slot"]) in taken or slot_is_past(r["date"], r["slot"]):
            continue
        out[r["date"]].append(r["slot"])
    return out


def _doctor_active(db, doctor_id):
    return db.execute(
        "SELECT 1 FROM doctors d JOIN users u ON u.id=d.user_id WHERE d.id=? AND u.is_active=1",
        (doctor_id,),
    ).fetchone()


def _patient_clash(db, patient_id, d, slot, ignore_id=None):
    return db.execute(
        "SELECT 1 FROM appointments WHERE patient_id=? AND date=? AND time=? AND status='Booked' AND id IS NOT ?",
        (patient_id, d, slot, ignore_id),
    ).fetchone()


def book(db, patient_id, doctor_id, d, slot, reason=""):
    if not _doctor_active(db, doctor_id):
        return False, "This doctor is not available."
    if slot not in available_slots(db, doctor_id).get(d, []):
        return False, "That slot is not available. Please pick another."
    if _patient_clash(db, patient_id, d, slot):
        return False, "You already have an appointment at that date and time."
    try:
        db.execute(
            "INSERT INTO appointments (patient_id, doctor_id, date, time, reason) VALUES (?,?,?,?,?)",
            (patient_id, doctor_id, d, slot, reason.strip()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return False, "Sorry, that slot was just taken."
    return True, "Appointment booked successfully."


def reschedule(db, appt, d, slot):
    if appt["status"] != "Booked":
        return False, "Only booked appointments can be rescheduled."
    if (d, slot) == (appt["date"], appt["time"]):
        return False, "Please choose a different date or time."
    if slot not in available_slots(db, appt["doctor_id"]).get(d, []):
        return False, "That slot is not available."
    if _patient_clash(db, appt["patient_id"], d, slot, appt["id"]):
        return False, "You already have an appointment at that date and time."
    try:
        db.execute("UPDATE appointments SET date=?, time=? WHERE id=?", (d, slot, appt["id"]))
        db.commit()
    except sqlite3.IntegrityError:
        return False, "Sorry, that slot was just taken."
    return True, "Appointment rescheduled."


APPT_SELECT = """
SELECT a.*, p.name AS patient_name, d.name AS doctor_name, dep.name AS dept,
       t.diagnosis, t.prescription, t.notes
FROM appointments a
JOIN patients p ON p.id = a.patient_id
JOIN doctors d ON d.id = a.doctor_id
LEFT JOIN departments dep ON dep.id = d.department_id
LEFT JOIN treatments t ON t.appointment_id = a.id
"""
