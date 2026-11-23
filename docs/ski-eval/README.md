# Ski eval results

Runs of the Ski eval ([`tests/ski_eval/`](../../tests/ski_eval)) against the real model,
from 2026-11-15. Claude Haiku 5.5, three runs per case, graded deterministically (no model judges).
Each file here is a compact copy of a workflow run's results; the full artifact (with the
grounding evidence and raw reply blocks) is linked from the file.

| Run | What changed | Main set (× 3 runs) | Held-out set (8 cases × 3) |
|---|---|---|---|
| [1](2026-11-15-1-first-run.json) | Nothing: Ski and graders as on `main` | 41/72 (57%) | n/a |
| [2](2026-11-15-2-before.json) | Graders and grounding check fixed; Ski unchanged | **66/72 (92%)** | **16/24 (67%)** |
| [3](2026-11-15-3-after.json) | Ski fixed | **64/72 (89%)** | **19/24 (79%)** |
| [4](2026-11-23-4-macro-crypto.json) | 2026-11-23: BLS/EIA macro data and crypto added; 3 new cases (27 in all) | **71/81 (88%)** | **21/24 (88%)** |

Runs 2 and 3 are both scored with the final graders (`run_eval.py --regrade`), so they compare
like with like. The held-out cases were written and committed (`0971bb3`) before any fix and
before Ski had answered them.

## Run 4: macro and crypto (2026-11-23)

- **The three new cases passed 9/9:** `oil-trend` (Ski reads the WTI series and names who gains and
  loses), `crypto-trend` (Ethereum's month in calendar days) and `crypto-vs-stocks` (correlation of
  BTC-USD with SPY and QQQ).
- One `crypto-vs-stocks` reply first failed on the grounding check: it called QQQ "the Nasdaq-100", and
  the "100" was taken for an invented figure. Index names are no longer read as figures; run 4 is
  scored with that fix, which changed only this reply.
- The fixture prices are synthetic, so BTC-USD comes out with a correlation of −0.67 and a beta of −3.97
  to the S&P 500. Ski reported them and called them unusually large rather than explaining them away.
- The scores match run 3 within noise. Every failure is a grounding flag; they were not checked by hand
  this time.

## What the first run measured

Most of run 1's failures were the grader, not Ski. Checked by hand, at least 23 of its 31
failed replies were correct (run 1 predates saving the evidence, so it can't be re-scored
mechanically): the format check rejected a bold `**Bottom line:**` that the chat card renders
fine; the grounding check didn't recognise "37%" as the probability 0.3684, or
"$470.65 − $465.07 = $5.58" as arithmetic on figures shown in the same sentence; one regex
missed "can't find". The fixes are tested both ways: each has a test where an invented figure
still fails. The arithmetic rule was measured before it was adopted: perturbing every figure in
run 1's replies by 2–20%, "any two figures may add up" passed 39% of the fakes; the rule used
(same unit, two decimals, inputs grounded and quoted in the reply) passes 0.4% and still passed
all 9 real derived figures.

## What changed in Ski

- **The what-if blind spot.** For signed-out visitors, the prompt said risk metrics were "not
  computed for the sample, so do not mention them", so Ski never called `portfolio_what_if`
  and did the maths by hand. What-if questions that called the tool: **3/9 → 9/9**.
- **Web answers repeated themselves.** Ski paraphrased a search result, then wrote the cited
  passage as a block of its own ("...0.39% borrow cost As of Oct 27, 2026, ORTEX estimated
  2.6%..."). Replies showing a repeated passage: **4 → 0**.
- **Sources are shown.** The chat card now links the pages a web answer cites.

## What the numbers don't say

- The main-set change (66 → 64 of 72) is noise: three runs per case can't separate two
  replies. The held-out gain (+3 runs) comes entirely from the what-if fix.
- Of run 3's 13 failures, **one is a wrong figure**: a bull call spread quoted at "$8.50 per
  share ($850 per contract)" when its legs ($3.12 − $0.60) and the tool both say about $2.52.
  The grounding check caught it. Nine are correct calculations the checker refuses by design
  (a one-decimal difference such as "RSI up 15.6 points", ratios such as "beta 1.36, so 36%
  more than the market"). Three are web figures for the VIX that can't be checked: the API
  truncates each citation's quoted text to about 150 characters, and one reply cited with
  markdown links instead of citations.
- 32 questions on fixture data is a small, hand-written set. It measures whether Ski uses its
  tools and quotes what they return, not whether its market commentary is good.

Reproduce: run the **Ski eval** workflow (`repeat=3`, `set=all`), or
`ANTHROPIC_API_KEY=... python tests/ski_eval/run_eval.py --repeat 3`, then
`python tests/ski_eval/run_eval.py --regrade <results.json>` to score a saved file with today's
graders. A full run costs well under a dollar.
