# VarianceLens — Forecast vs Actual Variance Explainer
## Product Brief

*Author: Vikram · October 2026 · Written before building — the prototype exists to test the thinking in this brief.*

---

## 1. Problem Statement

At every month-end review, leadership asks one question: **"Why did we miss the forecast?"** The finance analyst usually has the numbers within hours, but the *explanation* takes days. It means pulling variances category by category, splitting them into price and volume effects, checking whether a miss is real or just a timing shift, chasing business owners for context, and then writing a narrative that holds up under questioning.

Two things go wrong. Under time pressure, analysts **explain the biggest variance and miss the real driver** — for example, a large revenue miss that fully reverses next month (timing) gets the same attention as a permanent price erosion. And when the data doesn't explain a variance, there is pressure to **fill the gap with a plausible story** ("marketing overspent because of the promo"). When a story like that turns out to be wrong, the analyst loses credibility in the room.

Generic AI tools make the second problem worse: ask an LLM "why did revenue drop?" and it will confidently invent causes such as seasonality, competition or macro headwinds that appear nowhere in the data.

**Problem in one line:** analysts need to explain variances fast, but every cause they present must be traceable to the data — and today neither spreadsheets nor chatbots give them both.

---

## 2. User Persona

**Arjun, FP&A Analyst (mid-size consumer / D2C company, 4 years experience)**

| | |
|---|---|
| **Role** | Owns the monthly forecast-vs-actual pack for revenue and opex, 15–40 line items |
| **Tools** | Excel / Google Sheets exports from the ERP and planning tool; PowerPoint for the review deck |
| **Trigger moment** | Month-end review. The CFO asks: *"Why did we miss the forecast?"* — and then: *"Are you sure? Show me."* |
| **What he does today** | Sorts variances by size, computes price/volume by hand for a few lines, Slacks business owners for context, writes commentary in a text box the night before |
| **What he fears** | Presenting a cause that turns out to be wrong; being asked a follow-up he can't answer from the data |
| **What success looks like** | A 3-line explanation he can defend, where every number and every cause traces back to the data or to a documented note |

**Secondary user — FP&A lead / Admin:** wants to see which categories repeatedly miss, how much variance stays unexplained, and whether the tool's explanations are trusted by analysts.

---

## 3. JTBD Statement

> **When** I see variance between forecast and actuals at month-end,
> **I want to** explain what caused it — clearly and quickly — with each driver classified as volume, price, timing or anomaly,
> **so that** I can defend my analysis when leadership asks "why did we miss?" and "are you sure?".

**Functional job:** turn a forecast-vs-actual table into ranked, classified drivers with a short summary.
**Emotional job:** walk into the review confident that nothing in the explanation will collapse under a follow-up question.
**Social job:** be seen as the analyst whose numbers can be trusted.

**What the job is NOT:** inventing a story, forecasting next month, or replacing the analyst's judgement. When the data can't explain a variance, the product must say so and tell him what data to pull.

---

## 4. Why AI? (critical thinking)

Most of this job is arithmetic — and arithmetic should never be done by an LLM.

| Sub-task | Can rules / maths do it? | Decision |
|---|---|---|
| Validate input (numbers, duplicates, zero forecasts) | Yes | **Logic** |
| Calculate variance and % variance, favourable / unfavourable | Yes, exactly | **Logic** |
| Rank biggest contributors (share of total impact, Pareto 80%) | Yes | **Logic** |
| Split variance into price and volume effects (when units exist) | Yes — standard formula, sums exactly to the variance | **Logic** |
| Detect timing (monthly miss that YTD figures offset) | Yes — compare month vs YTD variance | **Logic** |
| Detect anomalies (variance far outside the other categories) | Yes — robust z-score | **Logic** |
| Read the analyst's free-text notes ("order shipped Oct 2") and link them to a driver | Partly — keywords catch most, but not all | **Logic first, AI to interpret** |
| Write a short, leadership-ready explanation in plain English | No | **AI** |
| Say what data would confirm an unexplained variance | No — needs reasoning | **AI** |
| Check that the AI used only real numbers and evidence-backed causes | Yes — number matching + evidence IDs | **Logic (after AI)** |

**Conclusion:** the logic layer *decides* (numbers, rankings, classifications, evidence). The AI only *writes* — it turns already-verified facts into a clear narrative and suggests what to investigate. The AI cannot create a cause: every causal statement must cite an evidence ID produced by the logic layer, or it is moved to a separate "hypotheses — not supported by data" section.

**Why not AI alone?** LLMs make arithmetic errors and invent plausible causes — exactly the key failure mode. **Why not logic alone?** Template sentences are accurate but stiff, and can't weave analyst notes into a 3-line story leadership will read. With no API key the app still works with templated explanations, which proves the logic layer is real.

---

## 5. Feature List + Value vs Effort

| # | Feature | User value | Effort | Priority |
|---|---|---|---|---|
| 1 | Structured data grid (category, type, forecast, actual, optional units, YTD, note) + CSV import + sample data | High | Medium | **MVP** |
| 2 | Logic: variance, % variance, favourable/unfavourable, totals, profit impact | High | Low | **MVP** |
| 3 | Logic: biggest contributors (share of impact, Pareto 80%), materiality thresholds | High | Low | **MVP** |
| 4 | Logic: price/volume decomposition, timing (YTD offset), anomaly (robust z), note keywords → evidence list | **Critical** | Medium | **MVP** |
| 5 | Classification per driver: volume / price / timing / anomaly — or "unexplained" when evidence is missing | **Critical** | Medium | **MVP** |
| 6 | AI-written headline + 2–4 sentence summary + per-driver explanation | High | Medium | **MVP** |
| 7 | Trust layer: number verification, evidence-ID check, causal-claim check, classification guard | **Critical** | Medium | **MVP** |
| 8 | Confidence score per driver and overall, plus "% of variance explained by data" | High | Low | **MVP** |
| 9 | "Hypotheses — not supported by data" + "data to request" panels | High | Low | **MVP** |
| 10 | Stored reports, history, copy-ready summary, CSV export | Medium | Low | **MVP** |
| 11 | Admin dashboard (usage, AI health, cost, classification mix, claims blocked, feedback) | Medium | Medium | **MVP** |
| 12 | Direct ERP / planning-tool connection | High | High | Later |
| 13 | Multi-period trend view (repeat offenders) | Medium | Medium | Later |
| 14 | Mix effect (product-mix decomposition) | Medium | Medium | Later |
| 15 | AI "guesses the cause" without evidence | Looks impressive | Low | **Deliberately not built** |

**Prioritisation logic:** everything that protects *traceability* (4, 5, 7, 8, 9) is in the MVP. A variance tool that sounds confident but invents a cause is worse than no tool — it gets the analyst caught out in front of the CFO.

---

## 6. Failure Mode Analysis

| Failure mode | Why it happens | Impact | Mitigation built into the product |
|---|---|---|---|
| **Inventing causes not supported by data (key failure mode)** | LLMs fill gaps with plausible stories ("seasonality", "competitive pressure") | Analyst presents a wrong cause → loses credibility; leadership makes a wrong decision | (a) Classification is done by the logic layer, not the AI. (b) The AI receives a numbered evidence list (E1, E2…) and every driver explanation must cite evidence IDs. (c) Explanations with causal words ("due to", "driven by") but no valid evidence are moved to **Hypotheses — not supported by data**. (d) If no evidence exists, the driver is labelled **Unexplained** with the data to request — never guessed. (e) The AI cannot change a data-backed classification; disagreements are logged and lower confidence. (f) Users rate each driver "Accurate / Cause is wrong"; the admin dashboard tracks the wrong-cause rate. |
| **Wrong numbers in the narrative** | LLM arithmetic / rounding errors | Destroys trust instantly | Every number in AI text is matched against computed values (tolerance for rounding, %, k/M). Sentences with unverified numbers are removed; if a whole explanation fails, a deterministic template replaces it. |
| **Explaining the biggest number, not the real driver** | Sorting by size ignores timing | Wasted debate on a miss that self-corrects | YTD offset check flags timing; profit impact (not raw size) drives ranking; materiality threshold set by the user. |
| **Mislabelled classification** | Only totals given, no units | False precision | Price/volume is only claimed when units exist; otherwise the evidence list says so and confidence drops. |
| **Bad input** (text in number cells, duplicates, zero forecast) | Messy exports | Garbage output | Validation gate with per-row errors before any AI call; zero forecasts handled (% shown as n/a). |
| **LLM down / timeout / bad JSON** | Network, quota, model change | Blank screen | Timeout + retry; on failure the full logic output is shown with templated explanations and a banner. |
| **Over-trust in confidence score** | Users read 80% as "certain" | Misplaced trust | Confidence shows *why* (evidence type, data coverage), plus "% of variance explained by data". |

---

## 7. AI Trade-offs

| Decision | Option chosen | Alternative | Why |
|---|---|---|---|
| Who classifies | Logic layer | LLM | Classification must be reproducible and auditable; the LLM can only comment. |
| Who calculates | Logic layer only | LLM | LLMs are unreliable at arithmetic; finance requires exact numbers. |
| AI role | Narrative writer + investigator ("what data to pull") | Root-cause engine | Root causes require evidence the model doesn't have. |
| Precision vs completeness | Prefer "Unexplained" over a guess | Always give a cause | The key failure mode is invented causes. An honest gap is defensible; a wrong cause is not. |
| Model | Small, cheap model (gpt-4o-mini class), configurable | Frontier model | The task is summarising a small verified table; small models do this well at low cost. |
| Temperature | 0.2 | Higher | Consistency over creativity. |
| Output | Strict JSON → rendered cards | Free text | Enables number and evidence checks before anything reaches the user. |
| Data sent to the AI | Computed table + evidence + notes only | Raw ledger | Less data = lower cost, less leakage risk, fewer distractions. |

---

## 8. Cost & Sustainability

**Per-report cost (gpt-4o-mini class pricing, ~$0.15 per 1M input / ~$0.60 per 1M output tokens):**

| Item | Tokens | Cost |
|---|---|---|
| System prompt + rules | ~1,000 | |
| Computed table (20 categories) + evidence list | ~1,800 | |
| Output (headline, summary, drivers, hypotheses) | ~900 | |
| **Total per report** | ~2,800 in / ~900 out | **≈ $0.001** |

- One analyst running 30 reports a month (re-runs included) ≈ **$0.03 / month**. A 20-person FP&A team ≈ **$0.60 / month**.
- Invalid data is rejected before the AI call → $0. All maths runs locally → free and instant.
- Every run logs tokens, latency and cost; the admin dashboard shows the running total.
- **Sustainability levers:** only material drivers are sent to the AI (not every row); cache by data hash; rules-only mode as a zero-cost tier; swap provider through an OpenAI-compatible base URL.
- **Data sensitivity:** financial actuals are confidential. Only aggregated category totals and notes are sent, never ledger lines. Production would add SSO and a provider with zero data retention.

**Value side:** month-end commentary typically takes an analyst several hours. Cutting the first draft to minutes, with traceable evidence, saves far more than the API cost. The real risk is credibility, not cost — which is why the trust layer gets most of the engineering.

---

## 9. Reflection

- **The maths was the easy part; honesty was the hard part.** It is trivial to make an LLM produce a confident variance story. The work went into making it *unable* to present a cause the data doesn't support.
- **"Unexplained" is a feature.** Saying "the data can't explain this — pull X" is more defensible in a CFO review than a plausible guess. Designing the UI to show that gap openly (instead of hiding it) was a deliberate choice.
- **Logic decides, AI writes.** Splitting the roles made the system testable: every classification can be reproduced from the inputs, and the AI's contribution is limited to language and suggested next steps.
- **Evidence IDs are the contract.** Giving the AI a numbered evidence list, and checking it cites them, turned a vague instruction ("don't make things up") into something code can verify.
- **What I'd do next:** add mix analysis, multi-month trends to spot repeat offenders, and test with 3–5 FP&A analysts to measure time-to-first-draft and how often a presented cause is later corrected.
- **What I'd measure:** (1) "cause is wrong" rate on rated drivers (target < 5%), (2) % of variance explained by data-backed drivers, (3) minutes from data upload to approved commentary.
