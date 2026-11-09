"""JSON REST API"""
import sqlite3
from flask import Blueprint, jsonify, request, g
from werkzeug.security import generate_password_hash
from db import get_db
import services
from services import APPT_SELECT

bp = Blueprint("api", __name__, url_prefix="/api")


def err(msg, code=400):
    return jsonify(error=msg), code


def need(role=None):
    if g.user is None:
        return err("Authentication required", 401)
    if role and g.user["role"] != role:
        return err("Forbidden", 403)


def doc_dict(r):
    return {k: r[k] for k in ("id", "name", "department_id", "dept", "experience", "qualification", "bio", "phone")}


DOC_SQL = ("SELECT d.*, dep.name AS dept FROM doctors d JOIN users u ON u.id=d.user_id "
           "LEFT JOIN departments dep ON dep.id=d.department_id WHERE u.is_active=1")


@bp.get("/departments")
def departments():
    if (e := need()):
        return e
    return jsonify([dict(r) for r in get_db().execute("SELECT * FROM departments ORDER BY name")])


@bp.get("/doctors")
def list_doctors():
    if (e := need()):
        return e
    q = f"%{request.args.get('q', '')}%"
    rows = get_db().execute(DOC_SQL + " AND (d.name LIKE ? OR dep.name LIKE ?) ORDER BY d.name", (q, q))
    return jsonify([doc_dict(r) for r in rows])


@bp.get("/doctors/<int:doctor_id>")
def get_doctor(doctor_id):
    if (e := need()):
        return e
    r = get_db().execute(DOC_SQL + " AND d.id=?", (doctor_id,)).fetchone()
    if not r:
        return err("Not found", 404)
    out = doc_dict(r)
    out["availability"] = services.available_slots(get_db(), doctor_id)
    return jsonify(out)


@bp.post("/doctors")
def create_doctor():
    if (e := need("admin")):
        return e
    j = request.get_json(silent=True) or {}
    if not j.get("name") or len(j.get("username", "")) < 3 or len(j.get("password", "")) < 6:
        return err("name, username (min 3) and password (min 6) are required")
    db = get_db()
    try:
        cur = db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?, 'doctor')",
                         (j["username"], generate_password_hash(j["password"])))
        c2 = db.execute(
            "INSERT INTO doctors (user_id, name, department_id, experience, qualification, bio, phone) VALUES (?,?,?,?,?,?,?)",
            (cur.lastrowid, j["name"], j.get("department_id"), int(j.get("experience", 0)),
             j.get("qualification", ""), j.get("bio", ""), j.get("phone", "")))
        db.commit()
    except (sqlite3.IntegrityError, ValueError):
        db.rollback()
        return err("Invalid data or username already exists")
    return jsonify(id=c2.lastrowid), 201


@bp.put("/doctors/<int:doctor_id>")
def update_doctor(doctor_id):
    if (e := need("admin")):
        return e
    j = request.get_json(silent=True) or {}
    db = get_db()
    r = db.execute("SELECT * FROM doctors WHERE id=?", (doctor_id,)).fetchone()
    if not r:
        return err("Not found", 404)
    db.execute("UPDATE doctors SET name=?, department_id=?, experience=?, qualification=?, bio=?, phone=? WHERE id=?",
               (j.get("name", r["name"]), j.get("department_id", r["department_id"]),
                j.get("experience", r["experience"]), j.get("qualification", r["qualification"]),
                j.get("bio", r["bio"]), j.get("phone", r["phone"]), doctor_id))
    db.commit()
    return jsonify(message="updated")


@bp.delete("/doctors/<int:doctor_id>")
def delete_doctor(doctor_id):
    if (e := need("admin")):
        return e
    db = get_db()
    r = db.execute("SELECT user_id FROM doctors WHERE id=?", (doctor_id,)).fetchone()
    if not r:
        return err("Not found", 404)
    db.execute("DELETE FROM users WHERE id=?", (r["user_id"],))
    db.commit()
    return jsonify(message="deleted")


@bp.get("/appointments")
def list_appointments():
    if (e := need()):
        return e
    role = g.user["role"]
    sql, params = APPT_SELECT, ()
    if role == "doctor":
        sql, params = sql + " WHERE a.doctor_id=?", (g.profile["id"],)
    elif role == "patient":
        sql, params = sql + " WHERE a.patient_id=?", (g.profile["id"],)
    rows = get_db().execute(sql + " ORDER BY a.date, a.time", params)
    return jsonify([dict(r) for r in rows])


@bp.post("/appointments")
def create_appointment():
    if (e := need("patient")):
        return e
    j = request.get_json(silent=True) or {}
    ok, msg = services.book(get_db(), g.profile["id"], j.get("doctor_id"), j.get("date", ""),
                            j.get("time", ""), j.get("reason", ""))
    return (jsonify(message=msg), 201) if ok else err(msg, 409)


@bp.patch("/appointments/<int:appt_id>")
def update_appointment(appt_id):
    """Doctors/admins set status (Completed/Cancelled); patients may only cancel their own."""
    if (e := need()):
        return e
    db = get_db()
    a = db.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if not a:
        return err("Not found", 404)
    role = g.user["role"]
    if (role == "doctor" and a["doctor_id"] != g.profile["id"]) or (role == "patient" and a["patient_id"] != g.profile["id"]):
        return err("Forbidden", 403)
    status = (request.get_json(silent=True) or {}).get("status")
    allowed = {"Cancelled"} if role == "patient" else {"Cancelled", "Completed"}
    if status not in allowed or a["status"] != "Booked":
        return err("Invalid status change")
    db.execute("UPDATE appointments SET status=? WHERE id=?", (status, appt_id))
    db.commit()
    return jsonify(message="updated")
