"""run with:  python app.py"""
import os
from flask import Flask, g, session, render_template
import db
from routes import auth, admin, doctor, patient, api


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.teardown_appcontext(db.close_db)
    db.init_db()

    @app.before_request
    def load_user():
        g.user = g.profile = None
        uid = session.get("user_id")
        if uid:
            d = db.get_db()
            user = d.execute("SELECT * FROM users WHERE id=? AND is_active=1", (uid,)).fetchone()
            if user is None:
                session.clear()
                return
            g.user = user
            if user["role"] == "doctor":
                g.profile = d.execute("SELECT * FROM doctors WHERE user_id=?", (uid,)).fetchone()
            elif user["role"] == "patient":
                g.profile = d.execute("SELECT * FROM patients WHERE user_id=?", (uid,)).fetchone()

    for bp in (auth.bp, admin.bp, doctor.bp, patient.bp, api.bp):
        app.register_blueprint(bp)

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, msg="You do not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, msg="Page not found."), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
