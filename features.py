"""Feature module: dashboard, compare analyses, export (JSON / TXT / CSV), account settings."""
import csv
import io
import json
from collections import Counter

from flask import (Blueprint, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from auth import login_required, password_problem
from db import get_db

bp = Blueprint("features", __name__)


def owned_row(aid):
    row = get_db().execute("SELECT * FROM analyses WHERE id=? AND user_id=?", (aid, g.user["id"])).fetchone()
    return row or abort(404)


def _download(body, mimetype, filename):
    return Response(body, mimetype=mimetype, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------------------------------------------------------------- dashboard
@bp.route("/dashboard")
@login_required
def dashboard():
    rows = get_db().execute("SELECT * FROM analyses WHERE user_id=? ORDER BY id DESC LIMIT 100",
                            (g.user["id"],)).fetchall()
    rows = list(reversed(rows))                                  # oldest -> newest for the trend line
    stats = None
    if rows:
        stats = {"count": len(rows),
                 "avg": round(sum(r["score"] for r in rows) / len(rows)),
                 "best": max(r["score"] for r in rows),
                 "quality": round(sum(r["quality"] for r in rows) / len(rows))}
    missing, matched = Counter(), Counter()
    for r in rows:
        data = json.loads(r["result_json"])
        missing.update(m["skill"] for m in data.get("missing", []))
        matched.update(m["skill"] for m in data.get("matched", []))
    W, H, P = 600, 190, 28                                      # trend chart geometry
    pts = []
    for i, r in enumerate(rows):
        x = W / 2 if len(rows) == 1 else P + i * (W - 2 * P) / (len(rows) - 1)
        y = H - P - r["score"] / 100 * (H - 2 * P)
        pts.append({"x": round(x, 1), "y": round(y, 1), "score": r["score"],
                    "label": f"{r['job_title'] or r['filename']}: {r['score']}%"})
    line = " ".join(f"{p['x']},{p['y']}" for p in pts)

    def top(counter):
        items = counter.most_common(8)
        biggest = items[0][1] if items else 1
        return [{"skill": s, "n": n, "pct": round(n / biggest * 100)} for s, n in items]

    return render_template("dashboard.html", stats=stats, pts=pts, line=line, W=W, H=H, P=P,
                           top_missing=top(missing), top_matched=top(matched), recent=rows[-5:][::-1])


# ---------------------------------------------------------------- compare
@bp.route("/compare")
@login_required
def compare():
    ids = request.args.getlist("ids", type=int)
    if len(set(ids)) != 2:
        flash("Select exactly two analyses to compare.", "error")
        return redirect(url_for("history"))
    a_row, b_row = owned_row(ids[0]), owned_row(ids[1])
    if a_row["id"] > b_row["id"]:                                # always older -> newer
        a_row, b_row = b_row, a_row
    a, b = json.loads(a_row["result_json"]), json.loads(b_row["result_json"])
    names = lambda r, k: {m["skill"] for m in r.get(k, [])}
    a_m, b_m = names(a, "matched"), names(b, "matched")
    diff = {"score": b["score"] - a["score"], "quality": b["quality"]["score"] - a["quality"]["score"],
            "skill": (b["skill_match"] or 0) - (a["skill_match"] or 0),
            "gained": sorted(b_m - a_m), "lost": sorted(a_m - b_m),
            "still_missing": sorted(names(a, "missing") & names(b, "missing"))}
    return render_template("compare.html", a=a, b=b, a_row=a_row, b_row=b_row, d=diff)


# ---------------------------------------------------------------- exports
@bp.route("/analysis/<int:aid>/export.json")
@login_required
def export_json(aid):
    row = owned_row(aid)
    return _download(json.dumps(json.loads(row["result_json"]), indent=2), "application/json",
                     f"analysis_{aid}.json")


@bp.route("/analysis/<int:aid>/export.txt")
@login_required
def export_txt(aid):
    row = owned_row(aid)
    r = json.loads(row["result_json"])
    L = ["RESUME ANALYSIS REPORT", "=" * 40, f"Job: {r.get('job_title') or '-'}",
         f"Resume: {row['filename']}   Date: {row['created_at']}", "",
         f"Overall match : {r['score']}%  ({r['verdict']})",
         f"Skill match   : {r['skill_match'] if r['skill_match'] is not None else '-'}%",
         f"Resume quality: {r['quality']['score']}/100", "",
         "MATCHED SKILLS", "-" * 14, ", ".join(m["skill"] for m in r["matched"]) or "none", "",
         "MISSING SKILLS", "-" * 14]
    L += [f"* {m['skill']} ({m['category']}): {m['tip']}" for m in r["missing"]] or ["none"]
    L += ["", "SUGGESTIONS", "-" * 11]
    L += [f"[{s['priority']}] {s['title']} - {s['detail']}" for s in r["suggestions"]] or ["none"]
    if r.get("ai"):
        L += ["", "AI RECRUITER REVIEW", "-" * 19, r["ai"]]
    return _download("\n".join(L) + "\n", "text/plain; charset=utf-8", f"analysis_{aid}.txt")


@bp.route("/history/export.csv")
@login_required
def export_csv():
    rows = get_db().execute("SELECT * FROM analyses WHERE user_id=? ORDER BY id", (g.user["id"],)).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "date", "job_title", "resume", "match_score", "quality_score"])
    for r in rows:
        # prefix risky cells so spreadsheets don't run them as formulas (CSV injection)
        safe = lambda v: ("'" + v) if isinstance(v, str) and v[:1] in "=+-@" else v
        w.writerow([r["id"], r["created_at"], safe(r["job_title"]), safe(r["filename"]), r["score"], r["quality"]])
    return _download(out.getvalue(), "text/csv; charset=utf-8", "analysis_history.csv")


# ---------------------------------------------------------------- account
@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        cur, new, new2 = (request.form.get(k, "") for k in ("current", "new", "confirm"))
        user = get_db().execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
        error = (("Current password is incorrect." if not check_password_hash(user["password_hash"], cur) else None)
                 or password_problem(new) or ("New passwords do not match." if new != new2 else None))
        if error:
            flash(error, "error")
        else:
            get_db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), g.user["id"]))
            get_db().commit()
            flash("Password updated.", "success")
        return redirect(url_for("features.account"))
    count = get_db().execute("SELECT COUNT(*) FROM analyses WHERE user_id=?", (g.user["id"],)).fetchone()[0]
    return render_template("account.html", count=count)


@bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    user = get_db().execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not check_password_hash(user["password_hash"], request.form.get("password", "")):
        flash("Password incorrect - account not deleted.", "error")
        return redirect(url_for("features.account"))
    db = get_db()
    db.execute("DELETE FROM analyses WHERE user_id=?", (g.user["id"],))
    db.execute("DELETE FROM users WHERE id=?", (g.user["id"],))
    db.commit()
    session.clear()
    flash("Your account and all its analyses were deleted.", "success")
    return redirect(url_for("auth.register"))
