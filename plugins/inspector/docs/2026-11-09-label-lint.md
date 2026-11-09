# Label lint for leads (2026-11-09)

`skills/inspect/scripts/lint_leads.py <leads.json | folder | ->` checks leads for label mistakes before a
person or a verifier spends time on them. One line per finding: `<where> | <rule> | <warn|info> | <message>`.
Exit 0 always; `--strict` exits 1 on any warn; invalid input exits 2. Pattern lists are constants at the top
of the script and each rule is a function, so each can be tested alone (`tests/test_lint_leads.py`).

## Rules

| Rule | Severity | Fires when |
|---|---|---|
| L1 | warn | category security and `security_actor` is missing or owner-like (owner, maintainer, we, our, the person, administrator ...) |
| L2 | warn | security, `needs_host_check`, level not reproduced, no `security_sink`: the consequence is not traced |
| L3 | warn | `reach` default-on while `reach_when` is set, or `what` mentions drift, varying model output, a rare input or a race |
| L4 | warn | level reproduced or read, no `probe` |
| L5 | info | `test_kind` text-pin and the `test` mentions no behavioral check |
| L6 | warn | level reproduced, impact level unverified, no needs-host-check |
| L7 | warn | 'documented', 'by design', 'intended' or 'pinned' in `what`/`breaks`, no `documented` field, no `reconcile` |
| L8 | warn | headline claim about a tool or flag (flag, `--x`, option, CLI) and no `probe`, or a probe that never names the flag |

The synthetic examples in `evals/label-lint/` (one lead per rule, `expected.json`) run in the fast lane.

## Measured on past runs

On 62 leads from five earlier runs, checked against independent verifiers, the lint flagged 5 of 14 label
failures overall (36%) and 27% (3 of 11) where the lead had the fields it needs, flagging 12% of the fine leads
in that view. Raw false alarms are higher (50%) because runs from before the `probe` and `security_actor` fields
existed trip L4, L8 and L1; the lint is a cheap first pass, since most label failures need the code to judge.
