"""VarianceLens — Forecast vs Actual Variance Explainer (Flask app entry point)."""
import csv
import hmac
import io
import os
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, flash, redirect, render_template, request, send_from_directory, session, url_for

import ai
import db
import logic
import pipeline

BASE = Path(__file__).parent
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
db.init_db()

app.jinja_env.filters["money"] = logic.money
app.jinja_env.filters["pct"] = logic.pct

CURRENCIES = ["INR", "USD", "EUR", "GBP", "AUD", "SGD"]
COLS = ["category", "type", "forecast", "actual", "forecast_units", "actual_units", "ytd_forecast", "ytd_actual", "note"]
SAMPLE_CSV = (BASE / "samples" / "sample_september.csv").read_text(encoding="utf-8")


def read_form():
    """Collect the report details and the data grid from the posted form."""
    meta = {k: (request.form.get(k) or "").strip() for k in ("title", "period", "entity", "currency", "mat_pct", "mat_abs")}
    if meta["currency"] not in CURRENCIES:
        meta["currency"] = CURRENCIES[0]
    cols = {c: request.form.getlist(c + "[]") for c in COLS}
    n = max((len(v) for v in cols.values()), default=0)
    rows = []
    for i in range(n):
        r = {c: (cols[c][i].strip() if i < len(cols[c]) else "") for c in COLS}
        if any(r[c] for c in COLS if c != "type"):  # skip fully empty rows
            rows.append(r)
    return meta, rows


def form_ctx(meta=None, rows=None, errors=None, row_errors=None):
    return dict(form=meta or {}, rows=rows or [], errors=errors or [], row_errors=row_errors or {},
                currencies=CURRENCIES, sample_csv=SAMPLE_CSV, active="new")


@app.route("/")
def index():
    meta, rows = {}, []
    src = request.args.get("from", type=int)
    if src:  # re-open a saved report's inputs to edit and re-run
        rep = db.get_report(src)
        if rep:
            meta, rows = rep["input"]["meta"], rep["input"]["rows"]
            meta = dict(meta, title=(meta.get("title") or "") + " (rev)")
    return render_template("index.html", **form_ctx(meta, rows), recent=db.list_reports(limit=5))


@app.route("/samples/<name>")
def static_sample(name):
    if name not in ("template.csv", "sample_september.csv"):
        abort(404)
    return send_from_directory(BASE / "samples", name, as_attachment=True)


@app.route("/analyze", methods=["POST"])
def analyze():
    meta, rows = read_form()
    errors = []
    if not meta["title"]:
        errors.append("Add a report title.")
    if len(rows) < 2:
        errors.append("Add at least two categories.")
    if errors:
        return render_template("index.html", **form_ctx(meta, rows, errors)), 400
    report = pipeline.analyze(meta, rows)
    if not report["ok"]:
        # rejected by the logic-layer gate: no AI call is made on bad data
        return render_template("index.html", **form_ctx(meta, rows, report["errors"], report["row_errors"])), 422
    try:
        report_id = db.save_report(meta, rows, report)
    except Exception as e:  # a storage failure must not lose the analysis
        app.logger.exception("save failed")
        flash(f"Report generated, but it couldn't be saved ({type(e).__name__}).", "warn")
        return render_template("result.html", **result_ctx(report, meta))
    return redirect(url_for("view_report", report_id=report_id))


@app.route("/report/<int:report_id>")
def view_report(report_id):
    rep = db.get_report(report_id)
    if not rep:
        flash("That report doesn't exist (it may have been deleted).", "error")
        return redirect(url_for("history"))
    meta = {k: rep[k] for k in ("title", "period", "entity", "created_at")}
    return render_template("result.html", **result_ctx(rep["result"], meta, report_id, db.feedback_for(report_id)))


@app.route("/report/<int:report_id>/feedback", methods=["POST"])
def feedback(report_id):
    rep = db.get_report(report_id)
    verdict, cat = request.form.get("verdict"), request.form.get("category", "")
    d = next((d for d in (rep or {}).get("result", {}).get("drivers", []) if d["category"] == cat), None)
    if not rep or not d or verdict not in ("accurate", "wrong_cause"):
        flash("Couldn't record that feedback.", "error")
    else:
        db.save_feedback(report_id, cat, verdict, d["classification"], d["explanation_source"])
    return redirect(url_for("view_report", report_id=report_id) + "#drivers")


@app.route("/report/<int:report_id>/export.csv")
def export_csv(report_id):
    rep = db.get_report(report_id)
    if not rep:
        abort(404)
    r = rep["result"]
    drivers = {d["category"]: d for d in r["drivers"]}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["category", "type", "forecast", "actual", "variance", "variance_pct", "profit_impact", "share_of_variance_pct",
                "material", "classification", "secondary", "confidence", "volume_effect", "price_effect", "explanation"])
    for row in r["rows"]:
        d = drivers.get(row["category"], {})
        w.writerow([row["category"], row["type"], row["forecast"], row["actual"], round(row["variance"], 2),
                    "" if row["pct"] is None else round(row["pct"], 2), round(row["impact"], 2), round(row["share"] * 100, 2),
                    row["material"], row.get("classification") or "", d.get("secondary") or "", d.get("confidence") or row.get("confidence") or "",
                    "" if row.get("volume_effect") is None else round(row["volume_effect"], 2),
                    "" if row.get("price_effect") is None else round(row["price_effect"], 2), d.get("explanation", "")])
    name = "".join(ch if ch.isalnum() else "_" for ch in rep["title"])[:60] or "report"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}_variance.csv"})


@app.route("/history")
def history():
    q = (request.args.get("q") or "").strip()
    return render_template("history.html", rows=db.list_reports(q), q=q, active="history")


def result_ctx(report, meta, report_id=None, feedback=None):
    return dict(r=report, meta=meta, classes=logic.CLASSES, ev={e["id"]: e for e in report["evidence"]},
                report_id=report_id, feedback=feedback or {}, active="new")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["is_admin"] = True
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/admin") else url_for("admin"))
        error = "Wrong password."
    return render_template("admin_login.html", error=error, default_pw=ADMIN_PASSWORD == "admin", active="admin")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    cfg = ai.config()
    status = {"ai_configured": bool(cfg["key"]), "model": cfg["model"],
              "db": "PostgreSQL" if db.IS_PG else f"SQLite ({Path(db.DB_PATH).name})",
              "default_pw": ADMIN_PASSWORD == "admin"}
    return render_template("admin.html", s=db.admin_stats(), rows=db.list_reports(limit=25), status=status,
                           classes=logic.CLASSES, active="admin")


@app.route("/admin/report/<int:report_id>/delete", methods=["POST"])
@admin_required
def admin_delete(report_id):
    db.delete_report(report_id)
    flash(f"Report #{report_id} deleted.", "ok")
    return redirect(url_for("admin"))


@app.route("/health")
def health():
    return {"status": "ok", "ai_configured": ai.available(), "db": "postgres" if db.IS_PG else "sqlite"}


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="That page doesn't exist."), 404


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500,
                           message="Something went wrong on our side. Go back and try again — your data was not changed."), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=os.environ.get("FLASK_DEBUG") == "1")
