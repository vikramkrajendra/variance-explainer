"""Run: python tests/test_logic.py"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import logic  # noqa: E402

META = {"title": "t", "mat_pct": "5", "mat_abs": "10000", "currency": "INR"}
ROWS = list(csv.DictReader(open(os.path.join(ROOT, "samples", "sample_september.csv"), encoding="utf-8")))


def by_cat(c):
    return {r["category"]: r for r in c["rows"]}


def test_variance_maths():
    r = by_cat(logic.run(META, ROWS))["Online sales"]
    assert r["variance"] == -150000 and round(r["pct"], 1) == -12.5 and r["impact"] == -150000


def test_cost_overrun_is_unfavourable():
    r = by_cat(logic.run(META, ROWS))["Paid marketing"]
    assert r["impact"] == -80000 and not r["favourable"]


def test_price_volume_sums_to_variance():
    for r in logic.run(META, ROWS)["rows"]:
        if "volume_effect" in r:
            assert abs(r["volume_effect"] + r["price_effect"] - r["variance"]) < 1e-6


def test_timing_from_ytd_offset():
    assert by_cat(logic.run(META, ROWS))["Wholesale"]["classification"] == "timing"


def test_no_evidence_means_unexplained_not_guessed():
    assert by_cat(logic.run(META, ROWS))["Paid marketing"]["classification"] == "unexplained"


def test_outlier_is_anomaly():
    assert by_cat(logic.run(META, ROWS))["Travel"]["classification"] == "anomaly"


def test_biggest_contributor_first():
    assert logic.run(META, ROWS)["drivers"][0] == "Wholesale"


def test_validation_gate():
    v = logic.run(META, [{"category": "A", "forecast": "x", "actual": "1"}, {"category": "a", "forecast": "1", "actual": "2"}])
    assert not v["validation"]["ok"] and len(v["validation"]["errors"]) >= 2


def test_parse_number_formats():
    assert logic.parse_number("(5,000)") == -5000 and logic.parse_number("₹1.2M") == 1.2e6 and logic.parse_number("") is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
