"""Authentication module: register, login, logout, login_required."""
import functools
import re
import time
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8
MAX_FAILS, WINDOW = 5, 300          # 5 wrong passwords per 5 minutes (per email + IP)
_FAILS = {}
_DUMMY_HASH = generate_password_hash("dummy-password")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def password_problem(pw):
    if len(pw) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if pw.isdigit() or pw.isalpha():
        return "Password must mix letters and numbers (or symbols)."
    return None


def _safe_next(target):
    if not target:
        return None
    p = urlparse(target)
    return target if not p.netloc and not p.scheme and target.startswith("/") and not target.startswith("//") else None


def _throttled(key):
    now = time.time()
    _FAILS[key] = [t for t in _FAILS.get(key, []) if now - t < WINDOW]
    return len(_FAILS[key]) >= MAX_FAILS


@bp.before_app_request
def load_user():
    uid = session.get("user_id")
    g.user = None
    if uid:
        g.user = get_db().execute("SELECT id,name,email,created_at FROM users WHERE id=?", (uid,)).fetchone()
        if g.user is None:
            session.clear()


def _start_session(user_id):
    session.clear()                  # drop any old session data (prevents session fixation)
    session["user_id"] = user_id
    session.permanent = True


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        email = request.form.get("email", "").strip().lower()[:200]
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        error = (("Enter your name." if not name else None)
                 or ("Enter a valid email address." if not EMAIL_RE.match(email) else None)
                 or password_problem(pw)
                 or ("Passwords do not match." if pw != pw2 else None))
        db = get_db()
        if not error and db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            error = "An account with this email already exists."
        if error:
            flash(error, "error")
            return render_template("register.html", name=name, email=email), 400
        cur = db.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                         (name, email, generate_password_hash(pw), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1:   # first user adopts pre-login history
            db.execute("UPDATE analyses SET user_id=? WHERE user_id IS NULL", (cur.lastrowid,))
        db.commit()
        _start_session(cur.lastrowid)
        flash(f"Welcome, {name}! Your account is ready.", "success")
        return redirect(url_for("index"))
    return render_template("register.html", name="", email="")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        key = f"{email}|{request.remote_addr}"
        if _throttled(key):
            flash("Too many failed attempts. Please wait a few minutes and try again.", "error")
            return render_template("login.html", email=email), 429
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, pw)
        if not (user and ok):
            _FAILS.setdefault(key, []).append(time.time())
            flash("Incorrect email or password.", "error")
            return render_template("login.html", email=email), 401
        _FAILS.pop(key, None)
        _start_session(user["id"])
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(_safe_next(request.args.get("next")) or url_for("index"))
    return render_template("login.html", email="")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()                  # removes the login and the CSRF token
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
