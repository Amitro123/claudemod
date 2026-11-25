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
| 2026-11-18 | #145 factory v2: intake, risk routing, issue queue, concurrent runs | none (4 of 4 answered; typesafe/jev-1.13, $0.0004; the diff was cut at 40k characters, so only its first part was seen) | — |
| 2026-11-19 | factory release 0.27.0 (version, changelog heading, descriptions) | none (4 of 4 answered; typesafe/jev-1.13, $0.0001) | — |
| 2026-11-18 | #144: `--recon`, `python` for Windows in printed commands, `SKILL.md` names premerge | untrusted-input 0.50 on the first run (4 of 4 answered; typesafe/jev-1.13, $0.0004), 0 yes after the fix | Yes, small. `INSPECTOR_PYTHON` was written raw into the commands the plan prints for an agent. Its value comes from the user's environment, not from the repository, but a value with shell syntax or broken quotes is now ignored, with tests. The second run flagged nothing |
| 2026-11-19 | #144 inspector: `--recon`, Windows interpreter in printed commands | none (4 of 4 answered; typesafe/jev-1.13, $0.0004) | — |
| 2026-11-19 | #148 `/inspector:audit`; new plugin retro (distill, agent-audit) | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; the diff was cut at 40k characters, so only its first part was seen) | — |
| 2026-11-19 | #148 again before merge: retro's tests in CI, main (#144) merged in | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — |
| 2026-11-19 | #149 retro: `/retro:board`, a shared fact board for sub-agents | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — |
| 2026-11-19 | #149 again: a second key for a fact already on the board is refused, `keys` | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — |
| 2026-11-19 | #149 before merge: the factory review's fixes, agents a plugin started | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — (the factory's code reviewer found two majors in agent-audit's board check, a substring match and blame for re-reading a record: logic, outside what these four ask) |
| 2026-11-19 | #150 factory: per-agent tool-call budgets, a FIXED ruling, validate skills-only plugins | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — |
| 2026-11-19 | #151 retro board: confirm records, last-confirmed time, `get --max-age` (built by a factory run) | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — (the factory's security reviewer found an uncaught OverflowError on a huge `--max-age`: input bounds, outside what these four ask) |
| 2026-11-19 | #170 factory: issue queue and PR step over gh api REST (built by a factory run from issue #152) | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — (the factory's security reviewer found the PR title in a double-quoted shell string in a handed-out command: outside text into a command, the kind the untrusted-input question asks about, but on a line this diff only rewrote; follow-up issue) |
| 2026-11-19 | #174 fix the open bugs: inspector audit, retro board, distill/agent-audit, factory (#153–#173) | failure-as-success (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | no: the fallbacks are `grep -v … \|\| true` in the session-link filter (grep exits 1 when every line is dropped; the branch is re-checked and the run stops if a link remains), an unreadable base (the builder goes as before) and a best-effort `run.json` save (only resume is lost) |
| 2026-11-19 | #174 again, after the factory review fixes (fb99376) | failure-as-success (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | yes, but the factory review got there first: its reviewers found the base check turning a new failure into an old one (fixed: compared by output) and the session-link scan going on when git log failed (fixed: it stops); the flag itself still points at the same fallbacks |
| 2026-11-19 | #175 factory: no 10-second filter-branch pause; retro: timestamps compared as instants | failure-as-success (4 of 4 answered; typesafe/jev-1.13, $0.0002) | no: `_instant(...) or 0.0` puts a call with an unreadable timestamp in the first dispatch, as the text comparison did before; the `\|\| true` in the alias is the msg-filter's, unchanged, and the branch is re-checked after |
| 2026-11-19 | #176 (meant for #175, which merged first): distill routes each lesson (check, test, access, guidance, skill, model, no-change), `lint_skill.py --recommendations` | none (4 of 4 answered; typesafe/jev-1.13, $0.0004) | — |
| 2026-11-20 | #176 again: an outside review's fixes (empty evidence or target; noprefix and octopus merges hiding secrets; truncated key masking; scratch paths) | none (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | — (all six were found by an outside review: parsing and git-configuration cases, outside what these four ask) |
| 2026-11-20 | #176 again: scanner matrix (and showRoot, textconv), factory keeps NOT CHECKED, optional follow-up issue | untrusted-input (4 of 4 answered; typesafe/jev-1.13, $0.0005; cut at 40k characters) | yes: the reviewers' text went into a public issue body as it was, so an `@name` in it would notify a real person and a newline could forge checklist items; fixed (one line, a zero-width space after `@`). No shell: `gh` gets argv and `-f` is a raw string |
| 2026-11-20 | #177 factory: base-check worktrees of their own, swept at session start; reviewers check parsers under other settings | none (4 of 4 answered; typesafe/jev-1.13, $0.0002) | — |
| 2026-11-20 | #177 again: retro scratch by location (R1), JSON masked value by value (R2) | none (4 of 4 answered; typesafe/jev-1.13, $0.0004) | — (both found by an outside recheck: a substring match and serialized-text masking, outside what these four ask) |
| 2026-11-20 | #178 release: factory 0.28.0, inspector 0.9.0, retro 0.3.0 | none (4 of 4 answered; typesafe/jev-1.13, $0.0002) | — |
| 2026-11-20 | #179 docs: rules with how each is held, factory stabilization plan, inspect case file | none (4 of 4 answered; typesafe/jev-1.13, $0.0004) | — (docs only) |
| 2026-11-20 | #180 inspector audit: the history scan reads files marked -diff or binary | none (4 of 4 answered; typesafe/jev-1.13, $0.0002) | — (the bug was found by /inspector:inspect, not by these four) |
| 2026-11-20 | #181 inspector, retro: tests that run on Windows, and a Windows job in CI | none (4 of 4 answered; typesafe/jev-1.13, $0.0001) | — (tests and CI only) |
| 2026-11-20 | #181 again: Windows CI fixes (golden normalizer, forbidden names, UTF-8 for every subprocess text call) | none (4 of 4 answered; typesafe/jev-1.13, $0.0005) | — (the encoding gap was found by the pytest-windows job, not by these four) |
| 2026-11-20 | factory tests: the engine fake keys files by one path form on Windows too (fix/factory-windows) | not run: INCOMPLETE, 0 of 4 answered (HTTP 401, no decision-model key on this machine) | — (nothing was checked; tests and CI only) |
| 2026-11-20 | #183 retro: mask() covers ghu_/ghs_/ghr_, Authorization headers and curl -u/--user | none (4 of 4 answered; typesafe/jev-1.13, $0.0004; run on 0bebcfc, after review round 2) | — (the round-2 findings, empty side of `-u`, other Authorization schemes, argument lists, a closing quote, came from the factory reviewers, outside what these four ask) |
| 2026-11-20 | #184 brain-hud redact_secrets: config-subcommand secrets, ?key=/?sig=, quoted Authorization, curl -u forms (PR #194) | none (4 of 4 answered; typesafe/jev-1.13, $0.0004; run on 2cc81a9, after review round 2) | — (the round-1 and round-2 majors, NTLM backslash, flag forms, greedy flag value, came from the factory reviewers, outside what these four ask) |
| 2026-11-22 | #185 inspector decide: scrub() masks credentials in every decision-model body (PR #199) | none (4 of 4 answered; typesafe/jev-1.13, $0.0006; run on 89fec99, after review round 4; the diff was cut at 40k characters, so INCOMPLETE: the check read only the start of the diff) | — (nothing changed because of it; the review rounds found the real issues, and this PR's diff is mostly a regex file and its tests, which the four questions do not cover) |
| 2026-11-25 | #200 inspector: one BOM-tolerant reader for run-folder JSON (`leadsio.read_json`), long Windows paths in prompts | none (4 of 4 answered; typesafe/jev-1.13, $0.0003; run on b6999ad) | — |
