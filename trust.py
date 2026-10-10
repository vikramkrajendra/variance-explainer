"""Trust layer — runs AFTER the AI and enforces the key rule: no cause or number the data doesn't support.

Checks, sentence by sentence:
1. Number verification — every number in AI text must match a value from the input or the
   logic layer (rounding-tolerant: 150K, 150,000, 0.15M, 12.5% all match). Sentences with an
   unverified number are removed.
2. Causal-claim check — a sentence that states a cause ("due to", "driven by", "because" …)
   must belong to a driver with supporting evidence AND cite that driver's evidence IDs.
   For unexplained / anomaly drivers every causal sentence is moved to Hypotheses.
   Cross-category causal links ("marketing rose because of the online promo") are moved too.
3. External-factor check — seasonality, competition, macro, weather … are moved to Hypotheses
   unless an analyst note mentions them.
4. Classification guard — the AI cannot change a classification; disagreement is logged and
   lowers confidence, or becomes a hypothesis when the logic layer found no evidence.
If an explanation loses most of its content, the logic-layer template explanation replaces it.
"""
from __future__ import annotations

import re

import logic

CAUSAL = re.compile(r"\b(because|due to|driven by|caused by|as a result of|owing to|result(ed|s)? (of|from)|attributable to|"
                    r"led to|stem(s|med)? from|on the back of|reflect(s|ing|ed)?|explained by|thanks to|following)\b", re.I)
EXTERNAL = re.compile(r"\b(season\w*|competit\w*|macro\w*|econom\w*|inflation|weather|holiday\w*|festive|market conditions|"
                      r"consumer sentiment|supply chain|geopolit\w*|recession|demand slowdown)\b", re.I)
NUM = re.compile(r"(?<![\w.])([-+−]?)(?:[A-Z]{3}\s?|[$₹€£]\s?)?(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
                 r"(%|k\b|K\b|m\b|M\b|mn\b|bn\b|B\b|million\b|billion\b|thousand\b|lakh\b|lakhs\b|crore\b|cr\b)?")
MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
        "lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "cr": 1e7}
SMALL_INT_OK = 12   # counts like "3 drivers", "top 2" are allowed


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def allowed_values(comp: dict, meta: dict, only: str | None = None) -> list[float]:
    """Numbers the text may use. With `only`, restricted to that category's row (+ totals, notes, meta):
    an explanation of Online sales must use Online sales numbers, not a coincidental match elsewhere."""
    vals = set()
    t = comp["totals"]
    for k, v in t.items():
        if isinstance(v, (int, float)) and v is not None:
            vals.add(abs(v))
            if k.endswith("share"):
                vals.add(abs(v) * 100)
    for r in comp["rows"]:
        if only and r["category"] != only:
            continue
        for k in ("forecast", "actual", "variance", "pct", "impact", "forecast_units", "actual_units", "ytd_forecast",
                  "ytd_actual", "volume_effect", "price_effect", "units_var", "units_pct", "fcst_price", "act_price",
                  "ytd_variance", "ytd_pct", "prior_months_variance", "z"):
            v = r.get(k)
            if isinstance(v, (int, float)):
                vals.add(abs(v))
        vals.add(r["share"] * 100)
        vals.add(abs(r["impact"]))
    for r in comp["rows"]:
        for m in NUM.finditer(r.get("note") or ""):   # numbers the analyst wrote are evidence too
            vals.add(_value(m))
    for m in NUM.finditer(" ".join(str(meta.get(k) or "") for k in ("title", "period", "entity"))):
        vals.add(_value(m))
    for s in (comp["settings"]["mat_pct"], comp["settings"]["mat_abs"]):
        vals.add(abs(s))
    return sorted(vals)


def _value(m) -> float:
    v = float(m.group(2).replace(",", ""))
    suf = (m.group(3) or "").lower()
    return v * MULT.get(suf, 1.0)


def _tolerance(m) -> float:
    raw = m.group(2).replace(",", "")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    unit = MULT.get((m.group(3) or "").lower(), 1.0)
    return 0.5 * (10 ** -decimals) * unit


def number_ok(m, allowed: list[float]) -> bool:
    v = _value(m)
    if v <= SMALL_INT_OK and float(v).is_integer() and not m.group(3):
        return True
    tol = max(_tolerance(m), 0.005 * v)
    return any(abs(v - a) <= tol for a in allowed)


def check_numbers(text: str, allowed, stats: dict, blocked: list, where: str) -> tuple[str, int]:
    """`allowed` is a list of values, or a function sentence -> list of values (context-aware checking)."""
    kept, dropped = [], 0
    for s in split_sentences(text):
        vals = allowed(s) if callable(allowed) else allowed
        bad = [m.group(0).strip() for m in NUM.finditer(s) if not number_ok(m, vals)]
        stats["numbers_checked"] += sum(1 for _ in NUM.finditer(s))
        if bad:
            stats["numbers_rejected"] += len(bad)
            dropped += 1
            blocked.append({"where": where, "text": s, "reason": f"number(s) not in your data for this context: {', '.join(bad)}"})
        else:
            kept.append(s)
    return " ".join(kept), dropped


def _mentions_other_category(sentence: str, own: str, categories: list[str]) -> str | None:
    for c in categories:
        if c != own and re.search(rf"\b{re.escape(c)}\b", sentence, re.I):
            return c
    return None


def apply(ai_out: dict, comp: dict, meta: dict, drivers: list[dict]) -> dict:
    cur = comp["settings"]["currency"]
    rows = {r["category"]: r for r in comp["rows"]}
    categories = sorted(rows, key=len, reverse=True)
    ev = {e["id"]: e for e in comp["evidence"]}
    notes_text = " ".join(r["note"] for r in comp["rows"])
    stats = {"ai_checked": True, "numbers_checked": 0, "numbers_rejected": 0, "claims_moved": 0,
             "class_conflicts": 0, "fallbacks": 0}
    blocked, hypotheses = [], []

    def move(category, sentence, reason, where):
        stats["claims_moved"] += 1
        blocked.append({"where": where, "text": sentence, "reason": reason})
        hypotheses.append({"category": category, "hypothesis": sentence, "data_to_confirm": "",
                           "source": f"Moved by trust layer — {reason}."})

    ai_by_cat = {d["category"]: d for d in ai_out["drivers"]}
    for d in drivers:
        a = ai_by_cat.get(d["category"])
        if not a:
            continue
        row = rows[d["category"]]
        own_ids = set(row["evidence_ids"])
        supporting = {i for i in own_ids if ev[i]["supports"]}
        cited = [i for i in a["evidence_ids"] if i in own_ids]
        invalid = [i for i in a["evidence_ids"] if i not in own_ids]
        if invalid:
            d["flags"].append(f"AI cited evidence that doesn't belong to {d['category']} ({', '.join(invalid)}) — ignored.")

        text, _ = check_numbers(a["explanation"], allowed_values(comp, meta, d["category"]), stats, blocked, d["category"])
        kept = []
        for s in split_sentences(text):
            causal = bool(CAUSAL.search(s))
            other = _mentions_other_category(s, d["category"], categories)
            if EXTERNAL.search(s) and not EXTERNAL.search(notes_text):
                move(d["category"], s, "external factor not mentioned anywhere in the data", d["category"])
            elif causal and d["classification"] in ("unexplained", "anomaly"):
                move(d["category"], s, f"states a cause, but no evidence explains {d['category']}", d["category"])
            elif causal and other and not any(other.lower() in ev[i]["text"].lower() for i in cited):
                move(d["category"], s, f"links {d['category']} to {other} without evidence connecting them", d["category"])
            elif causal and not (set(cited) & supporting):
                move(d["category"], s, "states a cause without citing supporting evidence", d["category"])
            else:
                kept.append(s)
        new = " ".join(kept)
        if new and d["classification"] in ("unexplained", "anomaly") and not re.search(r"\b(not|n't|no)\b.{0,40}\b(explain|evidence|data)", new, re.I):
            new += " The data doesn't explain this yet — see Data to request."
        if len(new) < 0.4 * len(a["explanation"]) or not new:
            d["explanation"] = d["template_explanation"]
            d["explanation_source"] = "ai_fallback"
            stats["fallbacks"] += 1
        else:
            d["explanation"] = new
            d["explanation_source"] = "ai"

        sc = a.get("suggested_classification")
        if sc and sc != d["classification"]:
            stats["class_conflicts"] += 1
            if d["classification"] == "unexplained":
                hypotheses.append({"category": d["category"],
                                   "hypothesis": f"AI suggests this may be {logic.CLASSES[sc].lower()}"
                                                 + (f": {a['classification_comment']}" if a["classification_comment"] else "."),
                                   "data_to_confirm": "", "source": "AI suggestion — no supporting evidence in the data."})
            else:
                d["flags"].append(f"AI suggested “{logic.CLASSES[sc]}”; kept “{logic.CLASSES[d['classification']]}” "
                                  f"because it is backed by the data.")
                d["confidence"] = round(max(0.3, (d["confidence"] or 0.3) - 0.1), 2)

    # headline + summary: numbers, unsupported causes about unexplained drivers, external factors
    weak = [d["category"] for d in drivers if d["classification"] in ("unexplained", "anomaly")]

    totals_only = allowed_values(comp, meta, only="\x00")   # totals + notes + meta, no row values

    def sentence_allowed(sentence):
        mentioned = [c for c in categories if re.search(rf"\b{re.escape(c)}\b", sentence, re.I)]
        if not mentioned:
            return totals_only
        vals = set(totals_only)
        for c in mentioned:
            vals.update(allowed_values(comp, meta, c))
        return sorted(vals)

    def clean_text(text, where):
        text, _ = check_numbers(text, sentence_allowed, stats, blocked, where)
        kept = []
        for s in split_sentences(text):
            hit = next((c for c in weak if re.search(rf"\b{re.escape(c)}\b", s, re.I)), None)
            if EXTERNAL.search(s) and not EXTERNAL.search(notes_text):
                move(hit or "Overall", s, "external factor not mentioned anywhere in the data", where)
            elif hit and CAUSAL.search(s):
                move(hit, s, f"states a cause for {hit}, which the data doesn't explain", where)
            else:
                kept.append(s)
        return " ".join(kept)

    headline = clean_text(ai_out["headline"], "headline")
    summary = clean_text(ai_out["summary"], "summary")
    if len(headline) < 25:
        headline = logic.headline(comp, cur)
        stats["fallbacks"] += 1

    # AI's own hypotheses: keep (they are already labelled as unverified) but number-check them
    for h in ai_out["hypotheses"]:
        txt, _ = check_numbers(h["hypothesis"], sentence_allowed, stats, blocked, "hypothesis")
        if txt:
            hypotheses.append({**h, "hypothesis": txt, "source": "AI hypothesis — verify before presenting."})

    requests_ = list(comp["data_requests"])
    have = {r["category"] for r in requests_}
    for q in ai_out["data_requests"]:
        if q["category"] in have:
            for r in requests_:
                if r["category"] == q["category"] and q["ask"] not in r["ask"]:
                    r["ask"] += " " + q["ask"]
        else:
            requests_.append(q)
            have.add(q["category"])

    stats["blocked"] = blocked[:20]
    return {"headline": headline, "summary": summary, "drivers": drivers, "hypotheses": hypotheses[:10],
            "data_requests": requests_, "trust": stats}
