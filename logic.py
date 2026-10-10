"""Logic layer — every number and every classification is decided here, BEFORE any AI call.

1. Validate and parse the grid (gate: bad data never reaches the AI).
2. Calculate variance, % variance, favourable/unfavourable and profit impact.
3. Identify the biggest contributors (share of total impact, Pareto 80%, materiality).
4. Build a numbered EVIDENCE list (E1, E2 …) from the data:
      price/volume decomposition (needs units) · YTD offset (timing) ·
      robust z-score outliers (anomaly) · keywords in analyst notes.
5. Classify each driver as volume / price / timing / anomaly — or "unexplained"
   when no evidence exists. A cause is never assumed.
"""
from __future__ import annotations

import math
import re
import statistics

CLASSES = {
    "volume": "Volume",
    "price": "Price",
    "timing": "Timing",
    "anomaly": "Anomaly",
    "unexplained": "Unexplained",
}
MAX_ROWS = 200
MAX_DRIVERS = 6
PARETO = 0.80
MIN_CLASS_SCORE = 0.45
ANOMALY_Z = 3.5
TIMING_OFFSET = 0.35  # YTD variance <= 35% of the month's variance -> earlier months offset it

NOTE_KEYWORDS = {
    "timing": r"slip\w*|delay\w*|shift\w*|pulled forward|pull-forward|deferr?\w*|accru\w*|early|late|next month|"
              r"previous month|prior month|instead of|in full|annual\w*|prepaid|catch-?up|timing|phasing|re-?phas\w*|"
              r"shipped (on )?\w+ \d|cut-?off",
    "price": r"price\w*|pricing|discount\w*|promo\w*|rate\w*|tariff|fx|exchange rate|currency|markdown\w*|rebate\w*|asp",
    "volume": r"units?|volume\w*|orders?|demand|traffic|customers?|churn\w*|headcount|hires?|stock-?outs?|footfall|"
              r"conversion|sold|lost (a )?(deal|customer|account)s?",
    "anomaly": r"error\w*|mis-?post\w*|mis-?class\w*|duplicate\w*|one-?off|one-?time|write-?off|reclass\w*|"
               r"wrong (account|entry|code)|data issue|fraud|unusual",
}
_NOTE_RES = {k: re.compile(rf"\b({v})\b", re.I) for k, v in NOTE_KEYWORDS.items()}

NUM_COLS = ("forecast", "actual", "forecast_units", "actual_units", "ytd_forecast", "ytd_actual")


# ---------------------------------------------------------------------------
# 1. Parsing + validation gate
# ---------------------------------------------------------------------------
def parse_number(s):
    """'1,20,000' '₹1.2M' '(5,000)' '-3k' '12%' -> float. Empty -> None. Raises ValueError otherwise."""
    if s is None:
        return None
    t = str(s).strip()
    if t == "":
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").replace(" ", "")
    t = re.sub(r"^[^\d\-+.]+", "", t)           # currency symbols / codes in front
    mult = 1.0
    m = re.match(r"^([-+]?\d*\.?\d+)(k|m|mn|bn|b|cr|l|lakh|lakhs)?%?$", t, re.I)
    if not m:
        raise ValueError(s)
    suffix = (m.group(2) or "").lower()
    mult = {"k": 1e3, "m": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9, "cr": 1e7, "l": 1e5, "lakh": 1e5, "lakhs": 1e5}.get(suffix, 1.0)
    v = float(m.group(1)) * mult
    return -v if neg else v


def validate(meta: dict, rows: list[dict]) -> dict:
    errors, warnings, row_errors, clean = [], [], {}, []
    if not meta.get("title"):
        errors.append("Add a report title.")
    try:
        mat_pct = parse_number(meta.get("mat_pct") or "5")
        mat_abs = parse_number(meta.get("mat_abs") or "0")
        if mat_pct is None or not 0 <= mat_pct <= 100 or mat_abs is None or mat_abs < 0:
            raise ValueError
    except ValueError:
        errors.append("Materiality thresholds must be numbers (0–100 for %, ≥ 0 for amount).")
        mat_pct, mat_abs = 5.0, 0.0
    if len(rows) < 2:
        errors.append("Add at least two categories — variance drivers only make sense in comparison.")
    if len(rows) > MAX_ROWS:
        errors.append(f"{len(rows)} rows — the limit is {MAX_ROWS}. Aggregate to category level first.")

    seen = {}
    for i, r in enumerate(rows):
        bad, label = [], r.get("category") or f"row {i + 1}"
        cat = (r.get("category") or "").strip()
        if not cat:
            bad.append("category"); errors.append(f"Row {i + 1}: category name is missing.")
        elif cat.lower() in seen:
            bad.append("category"); errors.append(f"Row {i + 1}: '{cat}' appears twice (also row {seen[cat.lower()] + 1}). Merge them.")
        else:
            seen[cat.lower()] = i
        typ = (r.get("type") or "revenue").lower()
        if typ not in ("revenue", "cost"):
            bad.append("type"); errors.append(f"{label}: type must be revenue or cost.")
        vals = {}
        for c in NUM_COLS:
            try:
                vals[c] = parse_number(r.get(c))
            except ValueError:
                bad.append(c); errors.append(f"{label}: '{r.get(c)}' in {c.replace('_', ' ')} is not a number.")
                vals[c] = None
        for c in ("forecast", "actual"):
            if vals[c] is None and c not in bad:
                bad.append(c); errors.append(f"{label}: {c} is required.")
        fu, au = vals["forecast_units"], vals["actual_units"]
        if (fu is None) != (au is None):
            bad += ["forecast_units", "actual_units"]
            errors.append(f"{label}: give both forecast and actual units, or neither.")
        elif fu is not None and (fu <= 0 or au < 0):
            bad += ["forecast_units", "actual_units"]
            errors.append(f"{label}: forecast units must be > 0 and actual units ≥ 0.")
        if (vals["ytd_forecast"] is None) != (vals["ytd_actual"] is None):
            bad += ["ytd_forecast", "ytd_actual"]
            errors.append(f"{label}: give both YTD forecast and YTD actual, or neither.")
        if bad:
            row_errors[i] = bad
            continue
        if vals["forecast"] == 0:
            warnings.append(f"{label}: forecast is 0, so % variance is shown as n/a.")
        clean.append({"category": cat, "type": typ, **vals, "note": (r.get("note") or "").strip()[:300]})

    if not errors and all(r["forecast"] == 0 for r in clean):
        errors.append("All forecasts are zero — there is nothing to compare against.")
    return {"ok": not errors, "errors": errors[:12] + ([f"…and {len(errors) - 12} more."] if len(errors) > 12 else []),
            "warnings": warnings, "row_errors": row_errors, "rows": clean,
            "settings": {"mat_pct": mat_pct, "mat_abs": mat_abs, "currency": meta.get("currency") or "INR"}}


# ---------------------------------------------------------------------------
# Formatting helpers (shared with templates and the trust layer)
# ---------------------------------------------------------------------------
def money(v, cur="", signed=True):
    if v is None:
        return "n/a"
    a = abs(v)
    s = f"{a / 1e9:.2f}B" if a >= 1e9 else f"{a / 1e6:.2f}M" if a >= 1e6 else f"{a / 1e3:.1f}K" if a >= 1e3 else f"{a:,.0f}"
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ("−" if v < 0 else "")
    return f"{sign}{cur + ' ' if cur else ''}{s}"


def pct(v, signed=True):
    if v is None:
        return "n/a"
    return f"{'+' if signed and v > 0 else '−' if v < 0 else ''}{abs(v):.1f}%"


# ---------------------------------------------------------------------------
# 2–5. Compute
# ---------------------------------------------------------------------------
def _robust_z(values: list[float]) -> list[float | None]:
    vals = [v for v in values if v is not None]
    if len(vals) < 4:
        return [None] * len(values)
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    if mad == 0:
        mad = statistics.mean([abs(v - med) for v in vals]) or 1.0
    return [None if v is None else round(0.6745 * (v - med) / mad, 2) for v in values]


def compute(clean_rows: list[dict], settings: dict) -> dict:
    cur = settings["currency"]
    rows = []
    for r in clean_rows:
        f, a = r["forecast"], r["actual"]
        var = a - f
        p = (var / abs(f) * 100) if f else None
        impact = var if r["type"] == "revenue" else -var
        row = {**r, "variance": var, "pct": p, "impact": impact,
               "favourable": impact > 0, "neutral": impact == 0}
        if r["forecast_units"] is not None:
            fu, au = r["forecast_units"], r["actual_units"]
            fp = f / fu
            vol = (au - fu) * fp                     # volume effect at forecast price
            price = var - vol                         # = (actual price − forecast price) × actual units
            row.update({"fcst_price": fp, "act_price": (a / au) if au else None, "volume_effect": vol,
                        "price_effect": price, "units_var": au - fu,
                        "units_pct": (au - fu) / fu * 100})
            tot = abs(vol) + abs(price)
            row["volume_share"] = abs(vol) / tot if tot else 0.5
            row["price_share"] = abs(price) / tot if tot else 0.5
        if r["ytd_forecast"] is not None:
            yv = r["ytd_actual"] - r["ytd_forecast"]
            row["ytd_variance"] = yv
            row["ytd_pct"] = (yv / abs(r["ytd_forecast"]) * 100) if r["ytd_forecast"] else None
            row["prior_months_variance"] = yv - var
        rows.append(row)

    for row, z in zip(rows, _robust_z([r["pct"] for r in rows])):
        row["z"] = z

    total_abs = sum(abs(r["impact"]) for r in rows) or 1.0
    for r in rows:
        r["share"] = abs(r["impact"]) / total_abs
        r["material"] = (abs(r["variance"]) >= settings["mat_abs"]) and (r["pct"] is None or abs(r["pct"]) >= settings["mat_pct"])

    # ---------------- evidence + classification ----------------
    evidence, eid = [], 0

    def add_ev(row, kind, text, supports, strength):
        nonlocal eid
        eid += 1
        e = {"id": f"E{eid}", "category": row["category"], "kind": kind, "text": text,
             "supports": supports, "strength": strength}
        evidence.append(e)
        row.setdefault("evidence_ids", []).append(e["id"])
        return e

    for r in rows:
        r["evidence_ids"] = []
        if not r["material"]:
            r["classification"], r["confidence"] = None, None
            continue
        scores = {"volume": 0.0, "price": 0.0, "timing": 0.0, "anomaly": 0.0}
        if "volume_effect" in r:
            add_ev(r, "price_volume",
                   f"Units {r['forecast_units']:,.0f} → {r['actual_units']:,.0f} ({pct(r['units_pct'])}); "
                   f"volume effect {money(r['volume_effect'], cur)}, price effect {money(r['price_effect'], cur)} "
                   f"(forecast price {money(r['fcst_price'], cur, False)}/unit"
                   + (f", actual {money(r['act_price'], cur, False)}/unit)" if r["act_price"] is not None else ")"),
                   ["volume", "price"], 0.9)
            scores["volume"] = 0.9 * r["volume_share"]
            scores["price"] = 0.9 * r["price_share"]
        if "ytd_variance" in r:
            offset = (r["variance"] != 0 and (math.copysign(1, r["ytd_variance"]) != math.copysign(1, r["variance"])
                      or abs(r["ytd_variance"]) <= TIMING_OFFSET * abs(r["variance"])))
            if offset:
                add_ev(r, "ytd", f"Month variance {money(r['variance'], cur)} but YTD variance only "
                                 f"{money(r['ytd_variance'], cur)} ({pct(r['ytd_pct'])}) — earlier months moved the "
                                 f"opposite way ({money(r['prior_months_variance'], cur)}), so this largely offsets.",
                       ["timing"], 0.8)
                scores["timing"] = max(scores["timing"], 0.8)
            else:
                add_ev(r, "ytd", f"YTD variance {money(r['ytd_variance'], cur)} ({pct(r['ytd_pct'])}) does not offset "
                                 f"this month — the gap is not reversing so far.", [], 0.5)
        if r["note"]:
            hits = [k for k, rx in _NOTE_RES.items() if rx.search(r["note"])]
            add_ev(r, "note", f"Analyst note: “{r['note']}”", hits, 0.65)
            for k in hits:
                if k in ("timing", "anomaly"):
                    bump = 0.65
                elif "volume_effect" in r:
                    bump = 0.05   # units data already measures price vs volume; a note only corroborates it
                else:
                    bump = 0.4
                scores[k] = min(0.95, scores[k] + bump)
        if r["z"] is not None and abs(r["z"]) >= ANOMALY_Z:
            add_ev(r, "stat", f"{pct(r['pct'])} is far outside the other categories (robust z-score {r['z']:.1f}).",
                   ["anomaly"], 0.55)
            scores["anomaly"] = max(scores["anomaly"], 0.55)
        if not r["evidence_ids"] or all(not e["supports"] for e in evidence if e["id"] in r["evidence_ids"]):
            missing = [x for x, ok in (("units", "volume_effect" in r), ("YTD", "ytd_variance" in r), ("note", bool(r["note"]))) if not ok]
            missing_txt = (", ".join(missing[:-1]) + " or " + missing[-1]) if len(missing) > 1 else (missing[0] if missing else "supporting")
            add_ev(r, "absence", f"No {missing_txt} data for {r['category']} — the cause can't be determined from the data.",
                   [], 0.0)

        primary = max(scores, key=scores.get)
        if scores["timing"] >= 0.75:
            primary = "timing"     # timing explains *why* volume/price moved this month
        best = scores[primary]
        if best < MIN_CLASS_SCORE:
            r["classification"], r["secondary"], r["confidence"] = "unexplained", None, 0.3
        else:
            r["classification"] = primary
            others = {k: v for k, v in scores.items() if k != primary and (
                v >= MIN_CLASS_SCORE or (k in ("volume", "price") and r.get(f"{k}_share", 0) >= 0.3))}
            r["secondary"] = max(others, key=others.get) if others else None
            n_kinds = len({e["kind"] for e in evidence if e["id"] in r["evidence_ids"] and primary in e["supports"]})
            r["confidence"] = round(min(0.95, best + 0.05 * (n_kinds - 1)), 2)
        r["scores"] = {k: round(v, 2) for k, v in scores.items()}

    # ---------------- drivers (biggest contributors) ----------------
    material = sorted([r for r in rows if r["material"]], key=lambda r: -abs(r["impact"]))
    drivers, cum = [], 0.0
    for r in material:
        if len(drivers) >= MAX_DRIVERS or (cum >= PARETO and drivers):
            break
        drivers.append(r)
        cum += r["share"]
    for i, r in enumerate(drivers, start=1):
        r["rank"] = i
        r["explanation"] = template_explanation(r, evidence, cur)

    rev = [r for r in rows if r["type"] == "revenue"]
    cost = [r for r in rows if r["type"] == "cost"]
    t = {
        "rev_forecast": sum(r["forecast"] for r in rev), "rev_actual": sum(r["actual"] for r in rev),
        "cost_forecast": sum(r["forecast"] for r in cost), "cost_actual": sum(r["actual"] for r in cost),
    }
    t["rev_variance"] = t["rev_actual"] - t["rev_forecast"]
    t["cost_variance"] = t["cost_actual"] - t["cost_forecast"]
    t["net_forecast"] = t["rev_forecast"] - t["cost_forecast"]
    t["net_actual"] = t["rev_actual"] - t["cost_actual"]
    t["net_variance"] = t["net_actual"] - t["net_forecast"]
    t["rev_pct"] = t["rev_variance"] / abs(t["rev_forecast"]) * 100 if t["rev_forecast"] else None
    t["cost_pct"] = t["cost_variance"] / abs(t["cost_forecast"]) * 100 if t["cost_forecast"] else None
    t["net_pct"] = t["net_variance"] / abs(t["net_forecast"]) * 100 if t["net_forecast"] else None
    t["drivers_share"] = sum(r["share"] for r in drivers)
    t["explained_share"] = sum(r["share"] for r in drivers
                               if r["classification"] in ("volume", "price", "timing") and (r["confidence"] or 0) >= 0.6)
    t["fav_impact"] = sum(r["impact"] for r in rows if r["impact"] > 0)
    t["unfav_impact"] = sum(r["impact"] for r in rows if r["impact"] < 0)
    return {"rows": rows, "drivers": [r["category"] for r in drivers], "evidence": evidence, "totals": t,
            "data_requests": data_requests(drivers),
            "stats": {"n_rows": len(rows), "n_material": len(material), "n_with_units": sum("volume_effect" in r for r in rows),
                      "n_with_ytd": sum("ytd_variance" in r for r in rows), "n_with_notes": sum(bool(r["note"]) for r in rows)}}


# ---------------------------------------------------------------------------
# Deterministic text (used in rules-only mode and as fallback for rejected AI text)
# ---------------------------------------------------------------------------
def template_explanation(r: dict, evidence: list[dict], cur: str) -> str:
    head = f"{r['category']} is {money(r['variance'], cur)} ({pct(r['pct'])}) vs forecast"
    head += f", {'favourable' if r['favourable'] else 'unfavourable'} by {money(abs(r['impact']), cur, False)} to profit."
    c = r["classification"]
    note = f" Analyst note: “{r['note']}”." if r["note"] else ""
    if c == "timing":
        if "ytd_variance" in r and any(e["kind"] == "ytd" and "timing" in e["supports"] for e in evidence if e["category"] == r["category"]):
            body = (f" Year-to-date it is only {money(r['ytd_variance'], cur)}, so earlier months offset most of it — "
                    f"a timing shift rather than a lasting miss.")
        else:
            body = " The analyst note points to timing (a shift between periods), not a lasting change."
        return head + body + note
    if c in ("volume", "price"):
        body = (f" Units moved {pct(r['units_pct'])}; volume explains {money(r['volume_effect'], cur)} and price "
                f"{money(r['price_effect'], cur)}.") if "volume_effect" in r else " The analyst note points to this driver."
        return head + body + note
    if c == "anomaly":
        return head + f" This is unusually large compared with the other categories and nothing in the data explains it — investigate before presenting." + note
    return head + " No units, YTD or notes explain it, so the cause can't be determined from the data yet." + note


def data_requests(drivers: list[dict]) -> list[dict]:
    out = []
    for r in drivers:
        if r["classification"] in ("unexplained", "anomaly"):
            asks = []
            if "volume_effect" not in r:
                asks.append("volumes / unit counts (to split price vs volume)")
            if "ytd_variance" not in r:
                asks.append("YTD forecast and actual (to test for timing)")
            asks.append("transaction-level detail or the budget owner's explanation")
            out.append({"category": r["category"], "ask": "Pull " + "; ".join(asks) + "."})
    return out


def headline(comp: dict, cur: str) -> str:
    t = comp["totals"]
    by_cat = {r["category"]: r for r in comp["rows"]}
    drv = [by_cat[c] for c in comp["drivers"]]
    parts = [f"{r['category']} ({CLASSES[r['classification']].lower()}, {money(r['impact'], cur)})" for r in drv[:3]]
    return (f"Net result is {money(t['net_variance'], cur)} vs forecast ({pct(t['net_pct'])}). "
            f"{'The biggest driver accounts' if len(drv) == 1 else f'The top {len(drv)} drivers account'} for "
            f"{round(t['drivers_share'] * 100)}% of all variance, led by " + "; ".join(parts) + ".")


def run(meta: dict, rows: list[dict]) -> dict:
    v = validate(meta, rows)
    if not v["ok"]:
        return {"validation": v}
    comp = compute(v["rows"], v["settings"])
    comp["validation"] = v
    comp["settings"] = v["settings"]
    return comp
