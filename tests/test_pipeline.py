"""Pipeline tests with a mocked LLM that deliberately invents causes and numbers.
Run: python tests/test_pipeline.py"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ai  # noqa: E402
import pipeline  # noqa: E402

META = {"title": "Sep close", "period": "Sep 2026", "entity": "India D2C", "currency": "INR", "mat_pct": "5", "mat_abs": "10000"}
ROWS = list(csv.DictReader(open(os.path.join(ROOT, "samples", "sample_september.csv"), encoding="utf-8")))

FAKE = {
    "headline": "We finished −INR 448.0K below forecast, mainly due to seasonal softness in demand.",
    "summary": ("The biggest gap is Wholesale (−INR 180.0K), which is timing: the Retailer X order shipped Oct 2. "
                "Revenue fell 15% overall. Paid marketing overspent because of the extended promo."),
    "drivers": [
        {"category": "Wholesale", "evidence_ids": ["E3", "E4", "E5"],
         "explanation": ("Wholesale is −INR 180.0K (−22.5%) vs forecast because the Retailer X order of 1,800 units shipped "
                         "Oct 2 instead of Sep 28. Year-to-date the gap is only −INR 10.0K, so this reverses next month.")},
        {"category": "Online sales", "evidence_ids": ["E1", "E2"],
         "explanation": ("Online sales missed by −INR 150.0K: fewer units drove −INR 100.0K and the extended promo discount "
                         "cost −INR 50.0K. Average selling price fell 7%.")},
        {"category": "Paid marketing", "evidence_ids": [], "suggested_classification": "volume",
         "classification_comment": "more campaigns were probably run",
         "explanation": "Paid marketing is +INR 80.0K (+32.0%) over plan. This was driven by the extended summer promo in Online sales."},
        {"category": "Travel", "evidence_ids": ["E10"],
         "explanation": "Travel is +INR 58.0K (+193.3%) over forecast. This reflects the festive season offsite."},
        {"category": "Marketplace", "evidence_ids": ["E6"], "suggested_classification": "volume",
         "explanation": "Marketplace beat forecast by +INR 45.0K with flat units, so the gain is entirely price."},
    ],
    "hypotheses": [{"category": "Travel", "hypothesis": "Was there a team offsite in September?", "data_to_confirm": "Travel bookings"}],
    "data_requests": [{"category": "Paid marketing", "ask": "Campaign-level spend by channel."}],
}


def run_with(content):
    os.environ["OPENAI_API_KEY"] = "test"
    orig = ai.call_llm
    ai.call_llm = lambda m: (content, {"prompt_tokens": 2800, "completion_tokens": 900})
    try:
        return pipeline.analyze(META, ROWS)
    finally:
        ai.call_llm = orig
        os.environ.pop("OPENAI_API_KEY", None)


def drv(r, c):
    return next(d for d in r["drivers"] if d["category"] == c)


def test_supported_explanations_survive():
    r = run_with(json.dumps(FAKE))
    assert r["mode"] == "ai"
    w = drv(r, "Wholesale")
    assert w["explanation_source"] == "ai" and "1,800 units" in w["explanation"]


def test_wrong_number_removed():
    r = run_with(json.dumps(FAKE))
    assert "7%" not in drv(r, "Online sales")["explanation"]
    assert "15%" not in r["summary"]
    assert r["trust"]["numbers_rejected"] >= 2


def test_invented_cause_for_unexplained_driver_moved_to_hypotheses():
    r = run_with(json.dumps(FAKE))
    pm = drv(r, "Paid marketing")
    assert "promo" not in pm["explanation"].lower()
    assert pm["classification"] == "unexplained"
    assert any(h["category"] == "Paid marketing" and "promo" in h["hypothesis"].lower() for h in r["hypotheses"])


def test_external_factor_blocked():
    r = run_with(json.dumps(FAKE))
    assert "season" not in r["headline"].lower() and "festive" not in drv(r, "Travel")["explanation"].lower()


def test_classification_cannot_be_overridden():
    r = run_with(json.dumps(FAKE))
    m = drv(r, "Marketplace")
    assert m["classification"] == "price" and m["flags"] and r["trust"]["class_conflicts"] >= 2


def test_bad_json_falls_back():
    r = run_with("not json at all")
    assert r["mode"] == "rules_only" and r["ai"]["called"] and r["drivers"]


def test_no_key_runs_logic_only():
    os.environ.pop("OPENAI_API_KEY", None)
    r = pipeline.analyze(META, ROWS)
    assert r["mode"] == "rules_only" and not r["ai"]["called"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    r = run_with(json.dumps(FAKE))
    print("\nheadline:", r["headline"])
    print("summary:", r["summary"])
    for d in r["drivers"]:
        print(f"- {d['category']} [{d['classification']}] ({d['explanation_source']}, conf {d['confidence']}): {d['explanation']}")
        for f in d["flags"]:
            print("    flag:", f)
    print("hypotheses:", json.dumps(r["hypotheses"], indent=1, ensure_ascii=False))
    print("trust:", {k: v for k, v in r["trust"].items() if k != "blocked"})
    for b in r["trust"]["blocked"]:
        print("  BLOCKED", b)
    print("confidence:", r["overall_confidence"], r["confidence_label"], r["confidence_reasons"])
