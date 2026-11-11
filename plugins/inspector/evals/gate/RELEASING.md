# Releasing the inspector plugin

A version bump is its own small PR, made only after every item below passes. The component tests
cover scripts one at a time; the checker covers the hand-offs between agents, files and scripts, where
past failures lived.

## Before a bump

1. **Full CI suite green** on the commit to be released: `python3 -m pytest tests -q` and
   `bash evals/run-offline.sh` from `plugins/inspector`, plus `claude plugin validate plugins/inspector`.
2. **`tests/test_doc_commands.py` passes.** It runs the commands the docs show, as written.
3. **Run-artifact check on a real or acceptance run.** Finish one parallel run (references/parallel.md,
   then verify.md), then:
   `python3 evals/gate/check_run.py <run folder>` (a run the collector planned has `plan/expect.json`; the reader ids,
   sweeper files and verifier chunks then come from it, and `plan.phases` fails when a phase left its outputs
   missing. For a run without a plan add `--expect <reader ids you started>`.)
   Exit 0 required: every invariant `pass` (a `skipped` one needs a written reason in the PR). Exit 1 is
   a finding to fix, exit 2 is a wrong invocation. The checker only reads the run folder. If a folder
   names files differently, pass `--override file.json`; do not edit the checker.
4. **Scorecard thresholds (proposals, not frozen).** Record the run with `evals/scorecard.py` and compare
   with the previous version. Starting points to calibrate after a few baseline runs: recall on planned
   bugs >= 75%, precision >= 70%, zero high-confidence leads on the control case, cost and wall time
   within about 30% of the known range. Below a proposal: explain it in the PR; nothing blocks on these yet.
5. **Changelog** has an entry for each change since the last release under `## Unreleased`.

## Who bumps and how

The maintainer bumps, in one commit named `release: inspector X.Y.Z`, touching only:
`plugins/inspector/.claude-plugin/plugin.json` (`version`), `plugins/inspector/CHANGELOG.md` (rename
`## Unreleased` to `## X.Y.Z (date)` and add a fresh empty `## Unreleased`), and the version mentions in
the root `README.md`. Look at the previous release commit (`git log --oneline -- plugins/inspector/.claude-plugin/plugin.json`)
and repeat its shape.

## Branch and merge rule

- A PR starts from a freshly fetched main: `git fetch origin && git switch -c <branch> origin/main`.
  Never stack it on another PR's branch: when the base merges first, a fix made on the stacked branch
  can be left out of main.
- After merging, verify the commit really is in main:
  `git fetch origin && git merge-base --is-ancestor <commit> origin/main && echo ok`
  Do this for every fix named in the changelog entry before tagging or announcing the release.
