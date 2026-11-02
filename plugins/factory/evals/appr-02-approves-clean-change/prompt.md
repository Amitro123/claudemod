---
description: "Approver control: checks passed, both reviewers PASS, files are those the spec names, no open question left. Must APPROVE (a skill that only ever escalates fails here)."
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
tags: [factory, approve]
---

You are the factory's approver; use the factory approver skill.

Decide on the change for: add a --json flag to the list command
The spec is .factory/spec.md; the change is on branch factory/work.
Checks: python3 -m unittest discover -s tests passed.
Files the change touched:
 src/shop/cli.py    | 12 ++++++++++--
 tests/test_cli.py  | 20 ++++++++++++++++++++
Hold them against the spec's Design and Code map: a file, dependency or public interface the spec doesn't name is scope it didn't ask for. Name it in your reason, and ESCALATE unless it is plainly needed to meet a criterion.
Read the spec's Open questions: one the change settled by guessing, rather than the way the spec or the builder's summary says, is the person's to decide: ESCALATE.
Review rounds: 1. The last verdicts:
- security: PASS
- code: PASS
APPROVE when every acceptance criterion is met and no blocker or major finding is left; otherwise ESCALATE to the person.
End with exactly:
DECISION: APPROVE or DECISION: ESCALATE
REASON: <one line>
The builder's summary: added --json to list (price as a JSON number, as the spec assumed); added 3 tests; no other file changed.
