---
description: "PR #3 fixed a crash that PR #2 (itself a fix) introduced when it rewrote total(). Expect the case to name #2 as the culprit, a fix-of-fix."
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
tags: [inspector]
---

Use the inspector's inspect skill. Investigate PR #3 of the repository you are started in: what it fixed, which earlier change caused the bug, and whether the same bug is still anywhere in today's code.
Work at most 3 cases. Write the case file to docs/inspector/case.md, in English. Nobody can answer questions during this run: where you would ask, take the default. Change no other file.
