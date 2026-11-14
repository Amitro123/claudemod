# Can a decision model tell REAL from REAL-LOW? (2026-11-14, a measurement: no)

## The question

Every verified run ends with about two dozen REAL-LOW leads beside a few REAL ones, and the person has to
find the ones worth fixing first. A decision model answers the fix / not-a-fix call well
(`evals/decision-fix`: typesafe/jev-1.13 found 20 of 20 fixes on unseen history). Could it also rank the
leads by severity, from the reader's text alone, before or instead of a verifier's judgement?

"Is this a false positive?" was not tested. Two runs had only two NOT REAL verdicts. Both were the same
artifact: the code was newer than the run's ref, and the bug was real at HEAD. There is nothing to filter,
and a wrong "false positive" would drop a real bug without a trace.

## Data

- **The leads:** 58, from the two inspections of #73–#123. Both runs used ref `dbf757a`, the same 12 cases
  and evidence, and verifiers on Sonnet.
- **Labels:** the verifier's verdicts. 10 REAL and 48 REAL-LOW. UNVERIFIABLE and NOT REAL are left out.
- **What the model saw:** each lead's text from `leads.json`, before any verifier: `where`, `what`, the
  claimed impact, `breaks`, `category`, `reach` and the reader's level.
- **The question:** one `noul` question per lead, all leads in one request through OpenRouter's Decisions
  API. The criteria were the verifier's own definitions from agents/verifier.md:
  - REAL: reachable in ordinary use, the stated impact holds.
  - REAL-LOW: narrower than claimed: a rare trigger, a small impact, opt-in, or hardening only.

## Result

| | recall (of 10 REAL) | precision | leads flagged |
|---|---|---|---|
| reader's `category: broken-flow` | **0.60** | **0.55** | 11 |
| reader's `level: reproduced` | 0.60 | 0.19 | 31 |
| reader's `reach: default-on` | 0.10 | 0.14 | 7 |
| jev-1.13, p >= 0.3 (two runs) | 0.80–0.90 | 0.29–0.32 | 28 |
| jev-1.13, p >= 0.5 | 0.20 | 0.25 | 8 |
| Gemini Decision 1, p >= 0.3 | 0.10 | 0.25 | 4 |

- **Ranking:** sorted by jev's probability, the REAL leads sit at a mean rank of about 18 of 58. A random
  order would put them at about 30. The ranks were 1, 5, 9, 13, 19, 21, 24, 26, 33, 39, and the second run
  was much the same. To catch 8 of 10, half the list has to be flagged, which saves almost nothing.
- **Cost:** under $0.001 per request for jev, $0.002 for Gemini.
- **The labels themselves are noisy.** Verifiers judged the same claim at `README.md:389` (the collector
  "offline") REAL once and REAL-LOW three times. A model can't learn a line that the verifiers don't draw
  consistently.

## What changed

`handoff.py` sorts by the labels the leads already carry. The order is:

1. seen in production
2. the verdict, REAL before REAL-LOW
3. `category: broken-flow` before the rest
4. level
5. reach

No model call is involved.

## Why

The fix call is a fact the text states: a title, commit subjects, the files changed. Severity is a claim
about what happens when the code runs. That takes reading the code and running it, which is the verifier's
work. The model only sees the reader's own wording, and that wording is written to sound real every time.

## Limits

- 58 leads from one repository and 12 cases, so 10 positives.
- The verdict labels disagree with themselves (above).
- Only the reader's text was given. A model that also saw the verifier's evidence would be judging the
  verifier, which is a different question.

Script and raw answers: kept outside the repository. Rerun by building the same inputs from a run folder's
`leads.json` and `merged.json`.
