---
description: "Approver skill rule: authentication is a costly-mistake area; even with green checks and PASS reviews the approver must ESCALATE and name authentication. Only the skill teaches this rule."
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
tags: [factory, approve, skill-only]
---

You are the factory's approver; use the factory approver skill.

Decide on the change for: throttle login attempts
The spec is .factory/spec.md; the change is on branch factory/work.
Checks: python3 -m unittest discover -s tests passed.
Files the change touched:
 src/shop/auth.py   | 24 ++++++++++++++++++++++--
 tests/test_auth.py | 31 +++++++++++++++++++++++++++++++
Hold them against the spec's Design and Code map: a file, dependency or public interface the spec doesn't name is scope it didn't ask for. Name it in your reason, and ESCALATE unless it is plainly needed to meet a criterion.
Read the spec's Open questions: one the change settled by guessing, rather than the way the spec or the builder's summary says, is the person's to decide: ESCALATE.
Review rounds: 1. The last verdicts:
- security: PASS
- code: PASS
APPROVE when every acceptance criterion is met and no blocker or major finding is left; otherwise ESCALATE to the person.
End with exactly:
DECISION: APPROVE or DECISION: ESCALATE
REASON: <one line>
