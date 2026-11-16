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
| 2026-11-15 | release 0.8.1 (version bump only) | not run | — |
| 2026-11-15 | SKILL: router budget + decision-model key; claim reasons on stdout | none (4 of 4 answered) | — |
| 2026-11-15 | needs_host_check written as the text "false" is no flag | none (4 of 4 answered; typesafe/jev-1.13, $0.0001) | — |
| 2026-11-15 | decision model: scrub emails, split a refused request, key with whitespace | none (4 of 4 answered; typesafe/jev-1.13, $0.0003) | — |
| 2026-11-15 | #137 + review fixes (split budget, request-wide refusals, cost after errors) | none (4 of 4 answered) | — (the budget bug was arithmetic in a retry loop: outside what these four ask) |
| 2026-11-15 | release 0.8.2 (version bump only) | none (4 of 4 answered) | — |
| 2026-11-15 | #140 (terms a non-fix unit removed from docs that other files still use) | none (4 of 4 answered; typesafe/jev-1.13, $0.0005) | — |
| 2026-11-15 | collector: batched git reads, blame memo for the per-file section | cache-key 0.52 (4 of 4 answered; typesafe/jev-1.13, $0.0003) | No. The flag is the new `_BLAME_MEMO`. Its key is the whole question blame is asked (fix commit, file at the parent, ranges); it is not written when an ignore-revs file is in use (the reader blames without one), a cut range or a renamed file misses and asks git, and `investigate()` empties it, so no entry outlives a run or crosses repositories |
| 2026-11-16 | duplicate leads merged by a decision model, labels normalized, docs answers to the handoff (same branch as the row above) | untrusted-input 0.50 (4 of 4 answered; typesafe/jev-1.13, $0.0005; the diff was cut at 40k characters) | Yes, small. The new duplicate question puts each lead's `where`, `what` and `impact` into the model's prompt with their line breaks, so a lead could forge a `## Pair N` heading and put its words into another pair's question. Each field is now one line, with a test. The other place outside text lands, a docs answer in the handoff table, already goes through `cell()` |
| 2026-11-16 | duplicate cut 0.75; one or two left-over leads share a verifier (same branch) | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; the diff was cut at 40k characters, so only its first part was seen) | — |
| 2026-11-16 | the docs-checker answers before its leads are verified; a `where` without a line number is compared (same branch) | none on the branch (4 of 4 answered; $0.0005; cut at 40k characters), and none on this commit alone, run with `--base HEAD~1` because the cut hid it (4 of 4 answered; $0.0003) | — |
| 2026-11-16 | resume restarts the docs-checker and holds its verifier; a recovered refusal leaves the decision model's cost incomplete | none (4 of 4 answered; typesafe/jev-1.13, $0.0003) | — (both were found by a review of 4ad47bd, not by this check: a missing dependency in a status report and an accounting gap are outside what these four ask) |
| 2026-11-16 | a `where` written as another path is compared; a merge before every verifier finished is refused; the verifier is told the allowed labels (same branch, this commit alone) | none (4 of 4 answered; typesafe/jev-1.13, $0.0003) | — |
