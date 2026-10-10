"""Pipeline: logic layer -> (AI layer) -> trust layer -> one structured report.

The report dict is what the UI renders and what the database stores.
"""
from __future__ import annotations

import time

import logic
from logic import money, pct


def confidence_label(c: float) -> str:
    return "High" if c >= 0.75 else "Medium" if c >= 0.55 else "Low"


def template_summary(comp: dict, cur: str) -> str:
    t = comp["totals"]
    by_cat = {r["category"]: r for r in comp["rows"]}
    drivers = [by_cat[c] for c in comp["drivers"]]
    open_items = [d["category"] for d in drivers if d["classification"] in ("unexplained", "anomaly")]
    s = (f"Revenue is {money(t['rev_variance'], cur)} ({pct(t['rev_pct'])}) and costs are "
         f"{money(t['cost_variance'], cur)} ({pct(t['cost_pct'])}) vs forecast. "
         f"{round(t['explained_share'] * 100)}% of the total variance is explained by data-backed drivers.")
    if open_items:
        s += f" {', '.join(open_items)} can't be explained from the data yet and need investigation before the review."
    return s


def build_drivers(comp: dict) -> list[dict]:
    by_cat = {r["category"]: r for r in comp["rows"]}
    out = []
    for c in comp["drivers"]:
        r = by_cat[c]
        out.append({
            "category": c, "rank": r["rank"], "type": r["type"],
            "classification": r["classification"], "secondary": r.get("secondary"),
            "confidence": r["confidence"], "base_confidence": r["confidence"],
            "variance": r["variance"], "pct": r["pct"], "impact": r["impact"], "share": r["share"],
            "favourable": r["favourable"],
            "volume_effect": r.get("volume_effect"), "price_effect": r.get("price_effect"),
            "volume_share": r.get("volume_share"), "price_share": r.get("price_share"),
            "explanation": r["explanation"], "template_explanation": r["explanation"],
            "explanation_source": "template", "evidence_ids": list(r["evidence_ids"]),
            "flags": [],
        })
    return out


def overall_confidence(report: dict) -> tuple[float, list[str]]:
    t = report["totals"]
    drivers = report["drivers"]
    reasons = []
    if not drivers:
        return 0.7, ["No material variances — nothing needed explaining."]
    w = sum(d["share"] for d in drivers) or 1
    avg = sum((d["confidence"] or 0.3) * d["share"] for d in drivers) / w
    coverage = t["explained_share"] / (t["drivers_share"] or 1)
    c = 0.6 * avg + 0.4 * coverage
    reasons.append(f"{round(t['explained_share'] * 100)}% of all variance is explained by data-backed drivers "
                   f"(price/volume split, YTD or analyst notes).")
    unexpl = [d["category"] for d in drivers if d["classification"] == "unexplained"]
    if unexpl:
        reasons.append(f"No evidence for {', '.join(unexpl)} — marked Unexplained instead of guessing.")
    st = report["stats"]
    if st["n_with_units"] == 0:
        reasons.append("No unit data was provided, so price vs volume can't be split.")
    trust = report.get("trust") or {}
    blocked = trust.get("numbers_rejected", 0) + trust.get("claims_moved", 0)
    if trust.get("ai_checked"):
        if blocked:
            c -= min(0.15, 0.05 * blocked)
            reasons.append(f"{blocked} AI statement(s) were blocked or moved to hypotheses because the data didn't support them.")
        else:
            reasons.append("Every number and cause in the AI narrative was verified against your data.")
    if trust.get("class_conflicts"):
        reasons.append(f"The AI disagreed with {trust['class_conflicts']} data-based classification(s); the data-based one was kept.")
    return round(max(0.05, min(0.97, c)), 2), reasons


def rules_only_report(comp: dict, cur: str, reason: str | None) -> dict:
    return {
        "mode": "rules_only",
        "headline": logic.headline(comp, cur),
        "summary": template_summary(comp, cur),
        "drivers": build_drivers(comp),
        "hypotheses": [],
        "data_requests": comp["data_requests"],
        "ai": {"called": False, "ok": False, "error": reason},
        "trust": {},
        "notices": [],
    }


def analyze(meta: dict, rows: list[dict]) -> dict:
    t0 = time.time()
    comp = logic.run(meta, rows)
    v = comp["validation"]
    if not v["ok"]:
        return {"ok": False, "errors": v["errors"], "row_errors": v["row_errors"]}
    cur = comp["settings"]["currency"]

    report = rules_only_report(comp, cur, None)

    report.update({"rows": comp["rows"], "evidence": comp["evidence"], "totals": comp["totals"],
                   "stats": comp["stats"], "settings": comp["settings"]})
    report["notices"] = v["warnings"] + report["notices"]
    report["overall_confidence"], report["confidence_reasons"] = overall_confidence(report)
    report["confidence_label"] = confidence_label(report["overall_confidence"])
    mix = {k: 0 for k in logic.CLASSES}
    for d in report["drivers"]:
        mix[d["classification"]] += 1
    report["class_mix"] = mix
    report["ok"] = True
    report["total_ms"] = int((time.time() - t0) * 1000)
    return report
