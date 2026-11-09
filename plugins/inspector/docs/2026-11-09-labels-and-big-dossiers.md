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
