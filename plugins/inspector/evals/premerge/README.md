# Pre-merge closed questions (`premerge.py`)

Can a decision model, asked closed questions about a change's diff, flag the changes that later needed a fix,
before they merge? Measured 2026-11-14. The questions come from the inspector's own case cards: each culprit
card records the wrong assumption the culprit made (`culprit.assumed`), and those assumptions fall into a few
kinds that are not specific to any one project.

## Data

- 107 changes: this repository's PR merges from #40, plus `a00de31`, and every first-parent unit of
  UltimateDocResearcher. Two culprits whose assumption fit no question (#97, #48) were left out of both sides.
- Positives: 15 culprit units the inspector named (cards of three runs on 2026-11-14), each mapped by hand to the
  question its recorded assumption is an instance of. That gives 23 culprit-question pairs. The mapping is in
  `run.py` (`POS`). Every other change is "not a known culprit", not "clean": a yes there is a false alarm or a
  bug nobody has found yet.
- Each change: its title and diff (stat and patch, lockfiles and images left out), cut at 40,000 characters
  (30 of the 107 were cut). One request per change, all questions in it, `typesafe/jev-1.13` through
  OpenRouter's Decisions API. Total cost $0.04.

`results-2026-11-14.json` holds every answer; `python3 -I run.py` repeats the run (it needs both checkouts).

## Results

How each question ranked the known culprits: the share of the other changes that got a lower probability (1.00:
every culprit above every other change), and how many of the 107 it answered yes at a cut of 0.5.

| Question (kind of wrong assumption) | Ranking | Flagged | Kept |
|---|---|---|---|
| A change elsewhere left docs, config, CI or tests behind | 1.00 | 2 | yes |
| A failure turned into a result that looks like success | 0.98 | 11 | yes |
| A cache key leaving out an input | 0.97 | 5 | yes |
| A call to an API the diff doesn't show is real | 0.93 | 27 | no: too many flags |
| Outside text written into code, a command or a prompt unescaped | 0.92 | 12 | yes |
| A second copy of a rule that exists | 0.79 | 8 | no |
| A fixed environment (path, id, sys.path, version) | 0.78 | 18 | no |
| State acted on after an await or a separate check | 0.74 | 44 | no: half the changes |
| Identity or safety decided by a pattern without variant tests | 0.74 | 56 | no: half the changes |
| A safety check made optional | 0.69 | 11 | no |

The four kept questions together, at a cut of 0.5: 26 of 107 changes flagged, 6 of the 7 culprit-question pairs
they cover answered yes. Two flags on changes not labelled as culprits were read: #85 on the cache key is a real
culprit (card #97 names it; it was missed in the labels), and `552e5b50` on outside text puts the research topic
into the Kaggle kernel id (a verified REAL-LOW). The other flags were not read.

The two bug families the 2026-11-14 inspection of this repository found most (a Stop undone after an await, and
regex guards) are the two questions that flagged half of everything: from a diff alone the model can't tell. For
those the guard is a test that covers the whole family (the route guard's corpus, the shared redaction cases).

## Limits

- 23 positive pairs, labelled by one person from the cards; small.
- Several culprit answers sit near the cut (0.51 to 0.53), and repeated runs of this model moved answers by up to
  0.13 (`evals/decision-fix`).
- Not yet measured going forward. The real test is the next changes: run `premerge.py` on each PR before merging
  and record, per flag, whether reading it found something worth changing. Add rows to the table below.

## Going forward

| Date | Change | Flags | Worth changing? |
|---|---|---|---|
| 2026-11-14 | #132 (R114-01..03, docs_question) | none | — (logic bugs: outside what these four ask) |
| 2026-11-15 | premerge incomplete report, O114-01, O114-02 | none (4 of 4 answered) | — (the recheck's finding was in premerge's own reporting: outside what these four ask) |
| 2026-11-15 | release 0.8.0 (version bump only) | none (4 of 4 answered) | — |
| 2026-11-15 | SKILL: router budget + decision-model key; claim reasons on stdout | none (4 of 4 answered) | — |
