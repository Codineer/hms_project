# Hospital Management System

A lightweight web app for handling hospital administrative tasks, doctor scheduling, and patient appointments. Built using Flask and SQLite with strict backend double-booking prevention.

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   python app.py
   ```

3. Open your browser and go to `http://127.0.0.1:5000`.

*Note: The SQLite database (`instance/hms.db`) initializes automatically on first run along with default seed data.*

### Default Admin Credentials
* **Username:** `admin`
* **Password:** `admin123`

---

## Roles & Permissions

* **Admin:** Manages doctor accounts, creates/edits department records, and oversees overall system data.
* **Doctor:** Sets availability slots, views patient appointments, and updates treatment records.
* **Patient:** Can self-register, search for doctors by department, and book available appointment slots.

---

## Project Structure

```text
├── app.py           # App factory, session initialization, error handlers
├── db.py            # Database setup, schema, and initial seeding script
├── services.py      # Core business logic (booking, rescheduling, auth decorators)
├── routes/          # Flask blueprints (auth, admin, doctor, patient, api)
├── templates/       # Jinja2 HTML templates
└── static/          # CSS / Bootstrap assets and client scripts
```

---

## Double-Booking Prevention

To ensure no two patients can book the same doctor for the same time slot, validation occurs at two levels:

1. **Application Level:** Checked dynamically in `services.py` during the booking process.
2. **Database Level:** Enforced via a SQLite partial unique index:
   ```sql
   CREATE UNIQUE INDEX uq_active_slot 
   ON appointments (doctor_id, date, time) 
   WHERE status IN ('Booked', 'Completed');
   ```

---

## API Overview

All API endpoints require active session authentication and return JSON.

| Method | Endpoint | Access | Description |
|---|---|---|---|
| GET | `/api/departments` | Public / All | List all hospital departments |
| GET | `/api/doctors?q=` | Public / All | Search doctors by query parameter |
| GET | `/api/doctors/<id>` | Public / All | Fetch details for a specific doctor |
| POST | `/api/doctors` | Admin | Create a new doctor profile |
| PUT | `/api/doctors/<id>` | Admin | Update existing doctor details |
| DELETE | `/api/doctors/<id>` | Admin | Remove a doctor profile |
| GET | `/api/appointments` | Scoped | Fetch appointments relevant to the logged-in user |
| POST | `/api/appointments` | Patient | Book a new appointment slot |
| PATCH | `/api/appointments/<id>` | Scoped | Cancel or modify an appointment status |