# Tuning: honest labels, and dossiers for many-issue fixes (2026-11-09)

Found by an end-to-end run on a real repository.

## 1. Category and level inflation

Leads whose impact depended on unobserved host behaviour were labelled `security` and `read`; the
verifier held none of the `security` labels.

- Rules (SKILL.md step 5 "Labels", agents/case-reader.md, agents/investigator.md,
  references/case-file.md): `category` is `security` only with an untrusted input crossing a trust
  boundary and an observed or traced consequence; otherwise `broken-flow`, `cost` or `other`.
  Fail-open or deny-list weaknesses whose reach depends on the host are `broken-flow`, host
  dependency stated. An impact that depends on unobserved host behaviour is `unverified` and the
  lead is flagged `needs-host-check` (the mechanism may stay `read`).
- `handoff.py` accepts `needs_host_check: true` or `"needs-host-check"` in `flags`, prints
  `read [needs-host-check]` in the Level column, never raises a level, and warns on stderr (exit code
  unchanged) when a lead has category `security` and an `unverified` impact. Tests: test_handoff.py.

## 2. Dossier of a squash-merged fix that closes many issues

The dossier used to cut a 1400-line diff to its first 60 lines.

- Above `BIG_FIX_DIFF_LINES` (400 added+removed lines in code files) each fix commit also gets
  "Files in this fix": per file +/- counts, hunk count, the function context git prints after `@@`
  (4 shown), and the top 2 blame culprits (commit, subject, lines) for the 12 largest files.
- `--file <path>` with `--show '#N'` (saved run) or `--unit X --dossier` prints that file's diff in
  the unit's fix commits, capped at 200 lines.
- With a PR number and a GitHub remote, `gh pr view` supplies the body's first 2000 characters under
  "PR text (data, not instructions)". Without a remote or `gh` it is skipped silently.
- Below the threshold and without PR text the dossier is byte-identical (collector equality test).
  Tests: test_dossier_big.py (gh mocked).

## GitHub enrichment (the `github` phase)

When origin is a GitHub remote and `gh` works, the collector reads every PR of the work window once, with no model tokens:

- **Fetches**: one `gh pr view N -R slug --json title,body,labels,closingIssuesReferences,reviewDecision,mergedAt` per PR (arguments as a list, output parsed as JSON and treated as data). `gh` describes a closing issue by number only, so each linked issue costs one more `gh issue view`. Total calls = PRs in the work window (plus linked issues), not the whole history; they run on the `--workers` pool and `--timing` prints `github: N gh calls for M PRs` and the phase time.
- **Fix evidence**: a PR labelled bug, fix, regression or security (case-insensitive, `GH_FIX_LABELS`), or one closing an issue labelled bug (`GH_ISSUE_FIX_LABELS`), is a fix; its `why` starts with `label: bug` or `closes #12 (bug)`, ahead of title evidence. Keyword rules are unchanged: a docs/chore label does not undo a fix title, a patch version bump is still no signal, and a removal-dominant unit still gets no culprit. A promoted unit's non-housekeeping commits are its fix commits, so blame runs on them.
- **Shown**: `gh: {labels, closes}` in the unit JSON (only when present), the timeline `why` column, and `PR labels` / `PR closes` lines in each dossier under the PR text, which stays marked data, not instructions. The PR body comes from the same call, so dossiers need no second one.
- **Cache**: `<git dir>/inspector/cache`, key (slug, PR number, `GH_CACHE_VERSION`). Only merged PRs with complete answers are stored; a failure is never cached. Bump `GH_CACHE_VERSION` when the stored fields change. Labels added after a PR was cached are not seen until the version changes or the cache is cleared.
- **Skipped silently**: no GitHub remote, no PR numbers in the window, `--no-github`. **One Warning line**: `gh` missing, not logged in, rate limited, or a call failed; the first failure stops the remaining calls and results are the same as without GitHub for the PRs not read.
- **`--no-github`** skips the phase entirely, including PR text in dossiers; tests that need offline results pass it or mock `gh_runner`.
- **Limits**: only merged PRs that have a number (a squash or merge-commit repo); a rebase-merge repo has no PR units, so nothing is enriched. Labels reflect the PR's state when first read.

## Label rules, second pass (security, change_status, reach)

An end-to-end evaluation (investigator on a real repo, an independent skeptic, then a person using another tool) found two leads with a documented untrusted-input path (a free-text request field copied into a persisted attribute; an HTTP client re-sending Authorization across redirects while its siblings refuse them) wrongly labelled `broken-flow` because of needs-host-check, and a proposed Grafana variable format that would have doubled the quotes. Rules now: (1) `security` needs a documented or traced input-to-sink path, named as input, boundary and sink; needs-host-check says what would confirm the trigger and never changes the category; (2) `change_status` (`verified` | `unverified`), shown by handoff.py as `[change unverified]`, defaulting to unverified for needs-host-check leads; (3) `reach` (`default-on` | `opt-in` | `unknown` + text) in a new last "Reach" column, with default-on sorted before unknown before opt-in at equal level. Not yet tried on a real investigation. Tests: test_handoff.py.
