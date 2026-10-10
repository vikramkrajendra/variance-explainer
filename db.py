"""Persistence — stores every variance report and per-driver feedback.

SQLite by default (file at DB_PATH, default data/variancelens.db).
If DATABASE_URL points to Postgres (e.g. Replit's built-in PostgreSQL, which you
need for a *deployed* app because deployments don't keep local files), it is used instead.
SQL is written once with :named params and translated per backend.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "data" / "variancelens.db"))

ID_COL = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
SCHEMA = [
    f"""CREATE TABLE IF NOT EXISTS reports (
        id {ID_COL},
        created_at TEXT NOT NULL,
        title TEXT NOT NULL,
        period TEXT,
        entity TEXT,
        currency TEXT,
        input_json TEXT NOT NULL,
        mode TEXT NOT NULL,
        model TEXT,
        net_variance REAL,
        net_pct REAL,
        rev_variance REAL,
        cost_variance REAL,
        overall_confidence REAL,
        confidence_label TEXT,
        explained_share REAL,
        n_rows INTEGER,
        n_drivers INTEGER,
        n_volume INTEGER,
        n_price INTEGER,
        n_timing INTEGER,
        n_anomaly INTEGER,
        n_unexplained INTEGER,
        n_hypotheses INTEGER,
        numbers_rejected INTEGER,
        claims_moved INTEGER,
        class_conflicts INTEGER,
        latency_ms INTEGER,
        tokens_in INTEGER,
        tokens_out INTEGER,
        cost_usd REAL,
        ai_error TEXT,
        result_json TEXT NOT NULL
    )""",
    f"""CREATE TABLE IF NOT EXISTS feedback (
        id {ID_COL},
        report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        classification TEXT,
        source TEXT,
        verdict TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (report_id, category)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at)",
]


def _connect():
    if IS_PG:
        import psycopg2  # only needed when DATABASE_URL is set
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _sql(q: str) -> str:
    return re.sub(r":(\w+)", r"%(\1)s", q) if IS_PG else q


@contextmanager
def _cursor():
    conn = _connect()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def init_db() -> None:
    with _cursor() as cur:
        for stmt in SCHEMA:
            cur.execute(stmt)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def save_report(meta: dict, rows: list[dict], r: dict) -> int:
    ai = r.get("ai") or {}
    t = r["totals"]
    tr = r.get("trust") or {}
    mix = r.get("class_mix") or {}
    row = {
        "created_at": now(), "title": meta.get("title", "")[:120], "period": meta.get("period", "")[:20],
        "entity": meta.get("entity", "")[:80], "currency": r["settings"]["currency"],
        "input_json": json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False),
        "mode": r["mode"], "model": ai.get("model"),
        "net_variance": t["net_variance"], "net_pct": t["net_pct"], "rev_variance": t["rev_variance"],
        "cost_variance": t["cost_variance"], "overall_confidence": r["overall_confidence"],
        "confidence_label": r["confidence_label"], "explained_share": t["explained_share"],
        "n_rows": r["stats"]["n_rows"], "n_drivers": len(r["drivers"]),
        "n_volume": mix.get("volume", 0), "n_price": mix.get("price", 0), "n_timing": mix.get("timing", 0),
        "n_anomaly": mix.get("anomaly", 0), "n_unexplained": mix.get("unexplained", 0),
        "n_hypotheses": len(r.get("hypotheses", [])),
        "numbers_rejected": tr.get("numbers_rejected", 0), "claims_moved": tr.get("claims_moved", 0),
        "class_conflicts": tr.get("class_conflicts", 0),
        "latency_ms": ai.get("latency_ms"), "tokens_in": ai.get("tokens_in"), "tokens_out": ai.get("tokens_out"),
        "cost_usd": ai.get("cost_usd"), "ai_error": ai.get("error"),
        "result_json": json.dumps(r, ensure_ascii=False, default=str),
    }
    cols = ", ".join(row)
    vals = ", ".join(f":{k}" for k in row)
    with _cursor() as cur:
        cur.execute(_sql(f"INSERT INTO reports ({cols}) VALUES ({vals}) RETURNING id"), row)
        res = cur.fetchone()
        return int(res["id"] if hasattr(res, "keys") else res[0])


def get_report(report_id: int) -> dict | None:
    with _cursor() as cur:
        cur.execute(_sql("SELECT * FROM reports WHERE id = :id"), {"id": report_id})
        rows = _rows(cur)
    if not rows:
        return None
    row = rows[0]
    row["result"] = json.loads(row.pop("result_json"))
    row["input"] = json.loads(row.pop("input_json"))
    return row


LIST_COLS = ("id, created_at, title, period, entity, currency, mode, model, net_variance, net_pct, rev_variance, "
             "cost_variance, overall_confidence, confidence_label, explained_share, n_drivers, n_volume, n_price, "
             "n_timing, n_anomaly, n_unexplained, n_hypotheses, numbers_rejected, claims_moved, latency_ms, cost_usd, ai_error")


def list_reports(search: str = "", limit: int = 50) -> list[dict]:
    q = f"SELECT {LIST_COLS} FROM reports"
    params = {"limit": limit}
    if search:
        q += " WHERE LOWER(title) LIKE :s OR LOWER(COALESCE(entity, '')) LIKE :s OR LOWER(COALESCE(period, '')) LIKE :s"
        params["s"] = f"%{search.lower()}%"
    q += " ORDER BY id DESC LIMIT :limit"
    with _cursor() as cur:
        cur.execute(_sql(q), params)
        return _rows(cur)


def delete_report(report_id: int) -> None:
    with _cursor() as cur:
        cur.execute(_sql("DELETE FROM feedback WHERE report_id = :id"), {"id": report_id})
        cur.execute(_sql("DELETE FROM reports WHERE id = :id"), {"id": report_id})


# ---------------------------------------------------------------------------
# Feedback — measures the key failure mode (wrong / invented causes)
# ---------------------------------------------------------------------------
def save_feedback(report_id: int, category: str, verdict: str, classification: str | None, source: str | None) -> None:
    p = {"r": report_id, "c": category[:120], "v": verdict, "k": classification, "s": source, "t": now()}
    with _cursor() as cur:
        cur.execute(_sql("DELETE FROM feedback WHERE report_id = :r AND category = :c"), p)
        cur.execute(_sql("INSERT INTO feedback (report_id, category, classification, source, verdict, created_at) "
                         "VALUES (:r, :c, :k, :s, :v, :t)"), p)


def feedback_for(report_id: int) -> dict:
    with _cursor() as cur:
        cur.execute(_sql("SELECT category, verdict FROM feedback WHERE report_id = :r"), {"r": report_id})
        return {r["category"]: r["verdict"] for r in _rows(cur)}
