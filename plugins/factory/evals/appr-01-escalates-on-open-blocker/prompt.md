---
description: "Approver consistency: checks green but the code reviewer still lists an open blocker after round 2. Must ESCALATE and name the blocker."
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
Review rounds: 2. The last verdicts:
- security: PASS
- code: CHANGES
  - [blocker] src/shop/cli.py:9 --json prints prices as strings, so acceptance criterion 1 (price 2.5 as a number) is not met
APPROVE when every acceptance criterion is met and no blocker or major finding is left; otherwise ESCALATE to the person.
End with exactly:
DECISION: APPROVE or DECISION: ESCALATE
REASON: <one line>
