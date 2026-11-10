# Handoff hardening (2026-11-10)

Four findings from an external review of the scripts that turn verified leads into the handoff.

- **Shared reader (INS-02).** `scripts/leadsio.py` is the one reader and validator for `lint_leads.py`,
  `handoff.py` and `crosscheck.py`. Input is `-`, a folder of `*.json`, or one `.json` file. A bad
  container exits 2 with `file[i].path: expected ...` before any output file is written.
- **Lint containers (INS-06).** `{"complete":{"siblings":"x"}}` and `siblings: [null]` now exit 2, with or
  without `--strict`. `[]`, `{}` and `siblings: []` stay valid.
- **Duplicates (INS-05).** `merge_verdicts.py` exits 2 for two leads with one `where` and for two different
  verdicts for one `where`. Identical duplicate verdicts are allowed. No lead id was added.
- **Handoff (INS-01).** `verifier: <evidence>` under the impact, `would settle: ...` for UNVERIFIABLE
  (from the new `verifier_unverifiable` field), and NOT REAL leads in a final "Rejected by the verifier"
  section instead of the action table. `--drop-not-real` still drops them entirely.

Tests: `tests/test_leadsio.py`, additions to `test_merge_verdicts.py` and `test_handoff.py`, and
`tests/test_verify_flow_e2e.py` (the documented commands as subprocesses).
