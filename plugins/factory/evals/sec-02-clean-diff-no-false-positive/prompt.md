---
description: "Security reviewer false-positive control: parameterized SQL, token from env, constant-time compare. Expect VERDICT PASS and no blocker/major."
max_turns: 15
allowed_tools: [Read, Glob, Grep, Skill]
tags: [factory, review, security]
---

You are the factory's security reviewer; use the factory security-reviewer skill.

Review the change for: add find_user for GET /user
The spec is .factory/spec.md. The change is the commits on branch factory/work, in the repository you are started in; its diff is in change.diff (you have no shell).
Files changed:
 app/auth.py        | 15 +++++++++++++++
 app/db.py          | 13 +++++++++++++
 tests/test_auth.py | 38 ++++++++++++++++++++++++++++++++++++++
Start from the diff and the spec's "Code map". Read a changed file whole when it is short (under about 400 lines), else around the changed lines; search before reading anything else.
Check every API field, input or type the change, or an acceptance criterion, relies on against its real definition (search for it and read the definition), not against the spec's wording: a criterion built on a field that doesn't exist is a blocker, and a test that only feeds a made-up fixture doesn't prove it.
Look only at what a security review covers. Don't change any file.
End your answer with exactly:
VERDICT: PASS or VERDICT: CHANGES
FINDINGS:
- [blocker|major|minor] <path:line> <what is wrong and why>
A blocker or major finding means CHANGES. Write "FINDINGS: none" when there are none.
