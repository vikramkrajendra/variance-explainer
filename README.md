# VarianceLens — Forecast vs Actual Variance Explainer

Explain *why* you missed the forecast — with every number and every cause traceable to the data.

| | |
|---|---|
| **User** | A finance analyst explaining differences between forecast and actuals |
| **Trigger** | Month-end review — leadership asks *"Why did we miss the forecast?"* |
| **JTBD** | When I see variance in numbers, I want to explain what caused it clearly and quickly, so I can defend my analysis. |
| **Key failure mode** | Inventing causes not supported by data |

📄 **Product brief:** [`docs/product-brief.pdf`](docs/product-brief.pdf) · 🎬 **Demo script:** [`docs/demo-script.md`](docs/demo-script.md)

## Why this product exists

Analysts can produce variance numbers in hours but need days to write an explanation they can defend. Under time pressure, gaps in the data get filled with plausible stories — and generic AI tools make that worse by inventing causes such as seasonality or competition. VarianceLens does the maths and classification deterministically, lets the AI only *write*, and blocks any cause the data can't support. When the data can't explain a variance, it says **Unexplained** and tells the analyst what to pull.

## How it works — logic decides, AI writes, trust layer verifies

```
Data grid ──► 1. LOGIC LAYER (logic.py)                      exact, free, auditable
              • gate: numbers, duplicates, unit/YTD pairs, materiality → bad data never reaches the AI
              • variance, % variance, favourable/unfavourable, profit impact, totals
              • biggest contributors: share of total impact, Pareto 80%, max 6, materiality filter
              • evidence list E1, E2 …:
                  price/volume split (units)   → volume / price
                  YTD offsets the month         → timing
                  robust z-score outlier        → anomaly
                  analyst-note keywords         → corroborates timing / price / volume / anomaly
              • classification from evidence only; no evidence → "Unexplained" (never guessed)
          ──► 2. AI LAYER (ai.py)                             one call, writes only
              • gets the computed table + classifications + evidence IDs
              • returns headline, summary, driver explanations citing evidence IDs, hypotheses, data requests
          ──► 3. TRUST LAYER (trust.py)                       blocks invented causes
              • every number checked against THIS driver's data (rounding-tolerant)
              • causal sentence without supporting evidence → moved to "Hypotheses — not supported by data"
              • any cause for Unexplained / Anomaly drivers → moved
              • cross-category links without evidence ("marketing rose because of the online promo") → moved
              • external factors (seasonality, competition, macro…) not in a note → moved
              • AI cannot change a classification; disagreement logged, confidence lowered
              • failed text replaced by the logic-layer template; AI down → logic-only report with banner
          ──► SQLite / Postgres (db.py) ──► report · saved reports · CSV export · admin dashboard
```

## Requirement checklist

| Requirement | Where |
|---|---|
| Accept forecast vs actual by category | Data grid on the home page (+ CSV import, template, sample) |
| Key variance drivers | Ranked driver cards + contributor chart |
| Classification volume / price / timing / anomaly | `logic.py`, shown as tags on drivers and in the table (plus honest "Unexplained") |
| Short explanation summary | "Why did we miss the forecast?" panel + copy-ready leadership text |
| Logic layer: % variance, biggest contributors | `logic.compute()`; visible in the full variance table and pipeline trace |
| Confidence score | Per driver (evidence strength) and overall (+ "% of variance explained by data") |
| Store reports | `db.py`; Saved reports page, permalinks, Edit & re-run, CSV export |
| Structured input, no raw JSON, error handling, admin dashboard | form grid · rendered cards · gate + AI fallback + 404/500 · `/admin` |

## Run on Replit

1. **Create App → Import from GitHub** and pick this repo.
2. **Tools → Secrets**: `OPENAI_API_KEY`, `ADMIN_PASSWORD`, `SECRET_KEY` (optional `OPENAI_MODEL`, default `gpt-4o-mini`; optional `OPENAI_BASE_URL` for any OpenAI-compatible provider).
3. **Run** — click "Load sample (Sep close)" → "Explain the variance".
4. For a permanent public link: add **PostgreSQL** (Tools → Database; sets `DATABASE_URL`) so reports survive, then **Deploy/Publish → Autoscale**.

Without a key the app runs in **logic-only** mode with templated explanations.

## Run locally

```bash
pip install -r requirements.txt
python main.py                                            # http://localhost:8080
python tests/test_logic.py && python tests/test_pipeline.py   # no network needed
```

`tests/test_pipeline.py` uses a mocked LLM that deliberately invents causes, wrong numbers and external factors — and checks that every one is blocked.

## Commit history (one per stage)

1. Product brief → 2. Input form → 3. Logic layer → 4. AI integration → 5. Database → 6. Dashboard
