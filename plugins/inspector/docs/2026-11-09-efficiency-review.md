# Inspector efficiency review — 2026-11-09

Reviewed commit: `9ad8d84c556b97f9ee8f4b99ad164b5d766a3c45`.

## Result

Inspector already delegates most mechanical work to stdlib Python: history traversal,
classification, blame, exact-copy search, triage, bounded dossiers, cross-checking and handoff.
The next useful improvement is reusing evidence and improving verification, not adding another
model layer. The README understates the current collector's triage and dossier capabilities.

## Verified locally

- Full repository clone succeeded. Original suite: 41 passed.
- Collector ran on the full current first-parent history: 82 units, 33 likely fixes.
  These are heuristic classifications, not verified bug counts.
- After changes: 47 passed, including golden tests against this repository's real history.
- One timing sample: collection 17.350 s; loading saved evidence and cross-checking an empty
  card list 0.0022 s. This measures avoided collection overhead, not model cost, nonempty
  cross-check throughput, or whole-investigation speedup.
- Updated collection produced exactly the same timeline as the baseline at the pinned SHA.
- Claude CLI is absent in this environment. No live Claude invocation, plugin validation,
  paid model eval, or token savings measurement was performed.

## Changes

1. Prefer the saved evidence for cross-checking. The old skill example recollected it even
   when saved evidence was available. Fallback accepts the original ref, unit and limits.
2. Pin collection to an immutable commit. Generated fallback commands retain the SHA,
   history/blame settings and shell-quote paths.
3. Compare PR numbers exactly. A card blaming #12 incorrectly agreed with blame's #1.
4. Keep every unreviewed copy location. Checking b.py must not silently clear c.py.
5. Render a root-commit culprit without asking for its nonexistent parent.

## Recommended next increments (not implemented)

| Priority | Change | Why | Acceptance |
|---|---|---|---|
| 1 | Persist investigated and deferred case IDs separately from the through-SHA | Incremental runs currently start after the checkpoint even when budget left older cases unworked | A second run retains deferred cases while avoiding completed ones |
| 1 | Add structured per-case evidence/probe fields and validate before rendering | JSON exists, but provenance and reproduction claims still rely on prose discipline | Missing probe or unsupported impact cannot become a verified finding |
| 2 | Cache selected PR metadata and failed CI excerpts | MCP currently enriches by model-driven calls; repeated retrieval costs context | Bounded selected-case retrieval, pagination/truncation recorded, cache keyed by repo/PR/update time |
| 2 | Measure Git subprocess counts, artifact bytes, model tokens, time and confirmed findings | Cost per confirmed useful finding matters more than main-context size | Comparable baseline and candidate runs on held-out histories |
| 3 | Cache immutable Git results or batch repeated grep queries | Collection computes metadata across the attribution window and performs many per-line greps | Same evidence, fewer subprocesses, cache invalidation covered by tests |

Use local Git for diffs and blame. Use GitHub MCP for information Git lacks: PR discussion,
linked issues, review comments and CI evidence. Restrict retrieval to selected cases and
expose only the needed read tools. MCP access itself is not a token optimization.

Keep semantic diagnosis with the model: the failing input, the promise it breaks, causality,
fix completeness and proposed regression test. Exact copied-line search is already automated;
semantic siblings still need code reasoning. Blame identifies the last writer, not necessarily
the change that introduced the bug.

Existing backtest results report clean-context workers finding more known bugs at higher
cost, but they concern one repository and repeated tuning. Treat them as encouraging local
evidence. Before changing routing or model choice, compare quality and cost on held-out
projects, including Hebrew prompts and a no-bug control. No routing change is included here.

## Follow-up: saved evidence and installed copies

Added in the cumulative patch (candidate version 0.3.1, not published):

- New evidence snapshots carry schema, plugin content fingerprint, plugin path/version,
  repository path, immutable ref and collection settings.
- Reuse rejects changed plugin files, unsupported schema, unavailable commit and explicit
  ref/path/since/unit mismatches. A moved clone can be selected explicitly with `--repo`.
- Historical HEAD and staged/unstaged/untracked edits produce warnings. The skill requires
  reading the snapshot commit or recollecting; committed history does not include local edits.
- Legacy evidence is readable but explicitly unverified. It must be recollected before relying
  on it. This is compatibility, not a guarantee of freshness.
- Atomic evidence writes preserve the previous file if replacement fails. Invalid saved JSON
  now produces a controlled CLI error for `--show`.
- `doctor.py` compares source/installed plugin contents, even under identical version numbers.
  It reports file identities, not which copy an existing Claude process has loaded.
- These protections are for artifact reuse; Inspector still has no automatic cross-run Git
  result cache. They neither control nor diagnose the model provider's prompt cache.

Validation: 62 tests in the full suite, including 15 new snapshot/local-copy tests. Scenarios
include dirty and moved checkouts, advanced HEAD, wrong repository, changed plugin files,
legacy/future formats, scope mismatch, interrupted replacement, and CLI error handling.
Claude runtime installation/reload remains unverified because this environment has no CLI.

Installation behavior was checked against the official loading reference on 2026-11-09:
https://code.claude.com/docs/en/plugins/loading
Remote marketplace installs normally load versioned copies; --plugin-dir and relative-path
plugins in a locally added marketplace load in place. Reload/session state is separate from
files on disk. No user cache was deleted and no local installation was changed.

## Follow-up: false-success and attribution checks

Reproduced nine failing regression scenarios before the fixes (two control scenarios already
passed). Added five further regression cases during verification. The full suite now passes
78 tests. These are deterministic code checks, not model evaluations.

- Offline wrapper now returns failure when validation fails even if pytest passes. Both checks
  still run. Wrapper tests use stub commands to independently vary their exit codes; they do
  not constitute live Claude validation.
- Malformed/partial card input and missing card directories fail before replacing an existing
  handoff or cross-check output. Object arrays in JSON files and stdin are handled consistently.
- Handoff writes are atomic; output write failures are no longer success exit codes.
- Copy decisions are scoped to their originating unit, commit, expression and location; checking
  the same line for one historical case does not clear another case automatically.
- A fix commit with no blame does not inherit the unit's other commits' blame.
- Commit matching uses the supplied prefix, rejecting ambiguous or absent commits instead of
  cutting every identifier to seven characters and selecting the first match.
- Cards identified only by a commit still leave their unreviewed copies visible.
- "Both unknown" is reported separately, not added to the count of corroborated culprits.

Remaining: persistent deferred-case queue, broader structured provenance for model claims,
optional bounded GitHub enrichment and held-out live Claude evals. No claims of measured model
cost savings or complete bug coverage are made.
