"""AI-Powered Resume Analyzer (Flask + SQLite) with login, dashboard, compare and export.
Resume files are processed in memory and never stored."""
import json
import os
import secrets
from datetime import datetime, timedelta

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

import analyzer
import auth
import db as database
import features
from auth import login_required
from db import get_db

BASE = os.path.dirname(os.path.abspath(__file__))


def load_secret_key():
    """SECRET_KEY env var, else a random key generated once and kept in .secret_key."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,                      # 5 MB
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
app.teardown_appcontext(database.close_db)
app.register_blueprint(auth.bp)
app.register_blueprint(features.bp)


def read_sample(name):
    try:
        with open(os.path.join(BASE, "samples", name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ------------------------------------------------------------------ CSRF protection
@app.context_processor
def inject_csrf():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return {"csrf_token": session["_csrf"]}


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf")
        if not token or not secrets.compare_digest(token, request.form.get("_csrf", "")):
            abort(400)


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if g.get("user"):
        resp.headers.setdefault("Cache-Control", "no-store")   # keep private pages out of shared caches
    return resp


@app.template_filter("when")
def when(v):
    try:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return v


# ------------------------------------------------------------------ core pages
@app.route("/")
@login_required
def index():
    return render_template("index.html", ai_on=analyzer.ai_enabled(),
                           sample_jd=read_sample("sample_job_description.txt"),
                           sample_resume=read_sample("sample_resume.txt"))


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    jd = request.form.get("job_description", "").strip()
    title = request.form.get("job_title", "").strip()[:120]
    pasted = request.form.get("resume_text", "").strip()
    file = request.files.get("resume")
    if len(jd) < 30:
        flash("Please paste a job description (at least a few lines).", "error")
        return redirect(url_for("index"))
    try:
        if file and file.filename:
            resume_text, fname = analyzer.extract_text(file.filename, file.read()), file.filename
        elif len(pasted) >= 40:
            resume_text, fname = pasted, "Pasted text"
        else:
            flash("Upload a resume file (PDF, DOCX, TXT) or paste your resume text.", "error")
            return redirect(url_for("index"))
    except analyzer.ExtractError as e:
        flash(str(e), "error")
        return redirect(url_for("index"))

    result = analyzer.analyze(resume_text, jd, title)
    if request.form.get("use_ai"):
        result["ai"] = analyzer.ai_review(resume_text, jd, result)
    db = get_db()
    cur = db.execute("INSERT INTO analyses(filename,job_title,score,quality,created_at,result_json,user_id) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (fname, title, result["score"], result["quality"]["score"],
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"), json.dumps(result), g.user["id"]))
    db.commit()
    return redirect(url_for("view", aid=cur.lastrowid))


@app.route("/analysis/<int:aid>")
@login_required
def view(aid):
    row = features.owned_row(aid)
    return render_template("result.html", r=json.loads(row["result_json"]), row=row)


@app.route("/history")
@login_required
def history():
    q = request.args.get("q", "").strip()
    sql, args = "SELECT * FROM analyses WHERE user_id=?", [g.user["id"]]
    if q:
        sql += " AND (job_title LIKE ? OR filename LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    rows = get_db().execute(sql + " ORDER BY id DESC LIMIT 100", args).fetchall()
    return render_template("history.html", rows=rows, q=q)


@app.route("/analysis/<int:aid>/delete", methods=["POST"])
@login_required
def delete(aid):
    features.owned_row(aid)
    get_db().execute("DELETE FROM analyses WHERE id=? AND user_id=?", (aid, g.user["id"]))
    get_db().commit()
    flash("Analysis deleted.", "success")
    return redirect(url_for("history"))


# ------------------------------------------------------------------ errors
@app.errorhandler(413)
def too_large(_e):
    flash("File too large (max 5 MB).", "error")
    return redirect(url_for("index"))


@app.errorhandler(400)
def bad_request(_e):
    return render_template("error.html", msg="Your session expired or the request was invalid. Please go back, refresh the page and try again."), 400


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", msg="Page not found."), 404


database.init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
