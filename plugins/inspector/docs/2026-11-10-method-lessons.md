# Method lessons from a field evaluation (2026-11-10)

Text-only edits to labels.md, producers.md, sweeper.md, investigator.md. Pins: tests/test_method_rules.py.

Evidence per edit (generic descriptions of what the evaluation showed):
1. Query stays unverified (labels.md): a query in a proposed test failed at run time although all text-pinning tests passed.
2. Production note sets observed_in_production (labels.md): a failure already recorded as seen in production was not ranked first.
3. Where logs live (producers.md 7): container logs were stored in a different workspace than the usage tables, so an alert on the wrong one would never fire.
4. Dated exceptions and reachability (sweeper.md 5): scanner exceptions had expired, and one named a library the code never imported.
5. Deploy order and skew (producers.md 8): additive columns, schema first, old image keeps working.
6. Same-role siblings (sweeper.md 6): a guard present in one of two clients but not the other; a check in one pipeline only.
7. Allowlist leads list all members (labels.md): a lead named one attribute while the allowlist had eight.
8. Degrade path failure modes (investigator.md): order dependence and collisions followed a fix that made a job refuse a whole batch on one bad record.

Not done, follow-up (needs scripts that another open change edits):
- lint_leads.py warning: a `verified` change or `text-pin` test whose text contains a query and no command.
- handoff.py sort refinement: `observed_in_production: yes` above a higher level lead with production `unknown` (today it sorts first only at equal level), so edit 2 is a method statement until then. (Done: `handoff.py` now sorts production `yes` before level.)
- Also later: scripts/suppressions.py (dated exceptions in collector output); eval fixtures for edits 1, 3, 4, 5, 6.
