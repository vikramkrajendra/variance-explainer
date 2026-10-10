# Demo video script (~6 minutes)

> To land under 5 minutes, skip the parts marked *(optional)*. Record with Loom; have the app, GitHub commits and the brief PDF open in tabs.

### 0:00 – 0:40 · The problem (brief, page 1)
"Every month-end, leadership asks one question: *why did we miss the forecast?* The numbers are quick; the explanation isn't. And when the data doesn't explain a variance, there's pressure to fill the gap with a plausible story. If that story is wrong, the analyst loses credibility in the room. My JTBD: when I see variance, I want to explain what caused it clearly and quickly, so I can defend my analysis."

### 0:40 – 1:20 · Why AI — and why the AI doesn't decide (brief, section 4)
"Most of this job is arithmetic, and an LLM should never do arithmetic for finance. So the logic layer calculates every variance, ranks contributors, splits price vs volume, detects timing from YTD and flags anomalies. The AI only *writes* — and every cause it states must cite evidence the logic layer produced. My key failure mode is inventing causes, so that's what the whole design protects against."

### 1:20 – 2:00 · Input form
- Show the structured grid: category, revenue/cost, forecast, actual — and the **optional evidence columns**: units, YTD, analyst note. "Without evidence, a cause can't be claimed."
- Click **Load sample (Sep close)**; point at materiality thresholds.
- *(optional)* Type "abc" in a forecast cell → submit → red cell + error. "Bad data never reaches the AI."

### 2:00 – 3:30 · The report
Submit. Walk top to bottom:
1. **Net −448K**, revenue and cost variance, **confidence** with "% of variance explained by data".
2. **Headline and summary**, then the reasons under it.
3. **Contributor chart**: Wholesale and Online sales are the biggest.
4. **Driver cards:**
   - *Wholesale → Timing*: month −180K, but YTD only −10K, plus the note "order shipped Oct 2". "It reverses — don't panic about it."
   - *Online sales → Volume + price*: the split bar shows volume −100K and price −50K.
   - *Paid marketing → Unexplained*: "no units, YTD or note. The tool refuses to guess."
   - *Travel → Anomaly*: +193%, z-score 6.6, investigate.
5. Each card shows **evidence IDs (E1, E2…)** and a confidence bar.

### 3:30 – 4:30 · The key failure mode, live (AI mode)
Scroll to **Hypotheses — not supported by data** and the trace's **Blocked AI statements** table:
- the AI wrote "Paid marketing overspent because of the extended promo" → **moved**: no evidence connects them;
- "seasonal softness" → **moved**: no note mentions seasonality;
- "Average selling price fell 7%" → **removed**: not in the data;
- the AI suggested re-classifying Marketplace as volume → **kept price**, because units were flat.
"This is the product: the AI can write, but it can't make things up."

### 4:30 – 5:00 · Logic layer is real
Expand **How this was analyzed** → evidence list. *(optional)* Show a report run without an API key: same numbers, drivers and classifications, with templated text.

### 5:00 – 5:40 · Stored reports + admin
- **Saved reports**, **Export CSV**, **Edit & re-run**.
- **Admin**: AI success rate, latency, cost (~$0.001 per report), classification mix, statements blocked, repeatedly unexplained categories, and the **wrong-cause rate** from 👍/👎 ratings.

### 5:40 – 6:10 · Build + close
Show the 6 GitHub commits: brief → form → logic → AI → database → dashboard.
"Logic decides, AI writes, and every cause traces to the data. Next I'd test with real FP&A analysts and measure how often a presented cause is later corrected."
