"""VarianceLens — Forecast vs Actual Variance Explainer (Flask app entry point)."""
import os
from pathlib import Path

from flask import Flask, abort, flash, render_template, request, send_from_directory, url_for

import logic
import pipeline

BASE = Path(__file__).parent
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

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
    return render_template("index.html", **form_ctx())


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
    return render_template("result.html", **result_ctx(report, meta))


def result_ctx(report, meta, report_id=None, feedback=None):
    return dict(r=report, meta=meta, classes=logic.CLASSES, ev={e["id"]: e for e in report["evidence"]},
                report_id=report_id, feedback=feedback or {}, active="new")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=os.environ.get("FLASK_DEBUG") == "1")
