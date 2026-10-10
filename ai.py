"""AI layer — one structured LLM call that WRITES, it does not decide.

The model receives the already-computed variance table, the logic layer's
classifications and a numbered evidence list (E1, E2 …). It writes the headline,
summary and driver explanations, and may only state a cause by citing evidence IDs.
Output is strict JSON, normalised here, then checked by trust.py.
Works with OpenAI or any OpenAI-compatible endpoint.

Env vars
  OPENAI_API_KEY      required for AI mode (otherwise the app runs rules-only)
  OPENAI_MODEL        default gpt-4o-mini
  OPENAI_BASE_URL     default https://api.openai.com/v1
  AI_TIMEOUT          seconds, default 45
  PRICE_IN_PER_M      USD per 1M input tokens, default 0.15
  PRICE_OUT_PER_M     USD per 1M output tokens, default 0.60
"""
from __future__ import annotations

import json
import os
import re
import time

import requests


class AIError(Exception):
    """Raised with a user-safe message when the AI layer can't produce a valid result."""


def config() -> dict:
    return {
        "key": os.environ.get("OPENAI_API_KEY", "").strip(),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip(),
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "timeout": float(os.environ.get("AI_TIMEOUT", "45")),
        "price_in": float(os.environ.get("PRICE_IN_PER_M", "0.15")),
        "price_out": float(os.environ.get("PRICE_OUT_PER_M", "0.60")),
    }


def available() -> bool:
    return bool(config()["key"])



CLASS_KEYS = ("volume", "price", "timing", "anomaly", "unexplained")

SYSTEM_PROMPT = """You are a senior FP&A analyst writing month-end variance commentary for leadership.
All numbers, rankings and classifications have ALREADY been calculated and are correct. Your job is to explain them clearly.

HARD RULES — the analyst must be able to defend every word in front of the CFO:
1. Use ONLY numbers that appear in the data provided. Never calculate new numbers, never round differently than shown, never estimate.
2. Never state a cause unless an evidence item supports it. Cite the evidence IDs you used (e.g. ["E2","E4"]) for every driver.
3. If a driver is classified "unexplained" or "anomaly", do NOT give a cause. Say plainly that the data does not explain it and what to check.
   Any possible cause you can think of goes ONLY into "hypotheses", phrased as a question to verify.
4. Do not link one category's variance to another category's note or variance unless an evidence item explicitly connects them.
5. Do not mention seasonality, competition, macro conditions, weather or any other external factor unless it appears in an analyst note.
6. Keep the classification given. If you believe the evidence points elsewhere, set "suggested_classification" and explain in "classification_comment"; the analyst decides.
7. Plain, confident, short. No hedging filler. Leadership reads 30 seconds of this.

Classifications: volume (more/fewer units), price (rate/price/discount per unit), timing (shift between periods that reverses), anomaly (unusual and unexplained by the data), unexplained (no evidence available).

Return ONLY JSON:
{
  "headline": "one sentence directly answering 'why did we miss the forecast?' using the net result and the top drivers",
  "summary": "2-4 sentences: what drove the gap, what is timing (will reverse) vs lasting, what is still unexplained",
  "drivers": [
    {"category": "exact category name", "explanation": "1-3 sentences using only provided numbers and cited evidence",
     "evidence_ids": ["E1"], "suggested_classification": null, "classification_comment": ""}
  ],
  "hypotheses": [{"category": "exact category name", "hypothesis": "possible cause phrased as something to verify", "data_to_confirm": "what to pull"}],
  "data_requests": [{"category": "exact category name", "ask": "specific data to pull before the review"}]
}"""


def _driver_payload(row: dict, cur: str) -> dict:
    from logic import money, pct
    d = {"category": row["category"], "type": row["type"], "classification": row["classification"],
         "secondary": row.get("secondary"), "forecast": money(row["forecast"], cur, False), "actual": money(row["actual"], cur, False),
         "variance": money(row["variance"], cur), "variance_pct": pct(row["pct"]), "profit_impact": money(row["impact"], cur),
         "share_of_total_variance": f"{round(row['share'] * 100)}%", "favourable": row["favourable"],
         "evidence_ids": row["evidence_ids"]}
    if "volume_effect" in row:
        d.update({"volume_effect": money(row["volume_effect"], cur), "price_effect": money(row["price_effect"], cur),
                  "units_change_pct": pct(row["units_pct"])})
    if "ytd_variance" in row:
        d["ytd_variance"] = money(row["ytd_variance"], cur)
    return d


def build_messages(meta: dict, comp: dict) -> list[dict]:
    from logic import money, pct
    cur = comp["settings"]["currency"]
    t = comp["totals"]
    by_cat = {r["category"]: r for r in comp["rows"]}
    payload = {
        "report": {"title": meta.get("title"), "period": meta.get("period"), "entity": meta.get("entity"), "currency": cur},
        "totals": {"revenue_variance": f"{money(t['rev_variance'], cur)} ({pct(t['rev_pct'])})",
                   "cost_variance": f"{money(t['cost_variance'], cur)} ({pct(t['cost_pct'])})",
                   "net_variance": f"{money(t['net_variance'], cur)} ({pct(t['net_pct'])})",
                   "drivers_share_of_total_variance": f"{round(t['drivers_share'] * 100)}%",
                   "explained_by_data": f"{round(t['explained_share'] * 100)}%"},
        "drivers_in_rank_order": [_driver_payload(by_cat[c], cur) for c in comp["drivers"]],
        "evidence": [{"id": e["id"], "category": e["category"], "text": e["text"]} for e in comp["evidence"]
                     if e["category"] in comp["drivers"]],
        "logic_data_requests": comp["data_requests"],
    }
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _post(cfg: dict, payload: dict) -> requests.Response:
    return requests.post(f"{cfg['base_url']}/chat/completions",
                         headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
                         json=payload, timeout=cfg["timeout"])


def _error_message(resp: requests.Response) -> str:
    try:
        return resp.json().get("error", {}).get("message", "")[:200]
    except ValueError:
        return resp.text[:200]


def call_llm(messages: list[dict]) -> tuple[str, dict]:
    """Return (content, usage). Retries once on rate-limit / server errors / timeouts."""
    cfg = config()
    if not cfg["key"]:
        raise AIError("No OPENAI_API_KEY configured")
    payload = {"model": cfg["model"], "messages": messages, "temperature": 0.2,
               "max_tokens": 2500, "response_format": {"type": "json_object"}}
    last = "unknown error"
    for attempt in range(2):
        try:
            resp = _post(cfg, payload)
        except requests.Timeout:
            last = f"the model did not respond within {int(cfg['timeout'])} s"
            continue
        except requests.RequestException as e:
            last = f"network error ({type(e).__name__})"
            continue
        if resp.status_code == 200:
            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raise AIError("the model returned an unexpected response shape")
            return content, data.get("usage") or {}
        msg = _error_message(resp)
        if resp.status_code == 400 and ("temperature" in msg or "max_tokens" in msg):
            # newer reasoning models reject these params — adapt and retry
            payload.pop("temperature", None)
            payload["max_completion_tokens"] = payload.pop("max_tokens", 2500) * 3
            continue
        if resp.status_code == 401:
            raise AIError("the API key was rejected (401) — check OPENAI_API_KEY")
        if resp.status_code == 404:
            raise AIError(f"model '{cfg['model']}' not found — check OPENAI_MODEL")
        if resp.status_code in (429, 500, 502, 503, 504):
            last = f"the AI provider returned {resp.status_code}" + (" (rate limit or quota)" if resp.status_code == 429 else "")
            time.sleep(1.5)
            continue
        raise AIError(f"the AI provider returned {resp.status_code}: {msg}")
    raise AIError(last)


# ---------------------------------------------------------------------------
# Parsing + schema validation
# ---------------------------------------------------------------------------
def parse_json(content: str) -> dict:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise AIError("the model's answer was not valid JSON")


def _f(x, default=0.5) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return default


def _s(x, limit=600) -> str:
    return str(x).strip()[:limit] if x is not None else ""


def normalise(raw: dict, categories: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise AIError("the model's answer had the wrong structure")
    canon = {c.lower(): c for c in categories}

    def cat(x):
        return canon.get(_s(x, 120).lower())

    drivers = []
    for d in raw.get("drivers") or []:
        if not isinstance(d, dict) or not cat(d.get("category")) or not _s(d.get("explanation")):
            continue
        sc = _s(d.get("suggested_classification"), 20).lower() or None
        drivers.append({"category": cat(d.get("category")), "explanation": _s(d.get("explanation"), 800),
                        "evidence_ids": [str(x) for x in (d.get("evidence_ids") or []) if re.fullmatch(r"E\d+", str(x))],
                        "suggested_classification": sc if sc in CLASS_KEYS else None,
                        "classification_comment": _s(d.get("classification_comment"), 300)})
    hyps = [{"category": cat(h.get("category")) or "Overall", "hypothesis": _s(h.get("hypothesis"), 300),
             "data_to_confirm": _s(h.get("data_to_confirm"), 300)}
            for h in raw.get("hypotheses") or [] if isinstance(h, dict) and _s(h.get("hypothesis"))]
    reqs = [{"category": cat(q.get("category")), "ask": _s(q.get("ask"), 300)}
            for q in raw.get("data_requests") or [] if isinstance(q, dict) and cat(q.get("category")) and _s(q.get("ask"))]
    if not drivers and not _s(raw.get("summary")):
        raise AIError("the model returned an empty explanation")
    return {"headline": _s(raw.get("headline"), 400), "summary": _s(raw.get("summary"), 1200),
            "drivers": drivers, "hypotheses": hyps, "data_requests": reqs}


def analyze(meta: dict, comp: dict) -> dict:
    cfg = config()
    t0 = time.time()
    content, usage = call_llm(build_messages(meta, comp))
    out = normalise(parse_json(content), {r["category"] for r in comp["rows"]})
    tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    out["ai"] = {"called": True, "ok": True, "model": cfg["model"], "latency_ms": int((time.time() - t0) * 1000),
                 "tokens_in": tin, "tokens_out": tout,
                 "cost_usd": round(tin / 1e6 * cfg["price_in"] + tout / 1e6 * cfg["price_out"], 6)}
    return out
