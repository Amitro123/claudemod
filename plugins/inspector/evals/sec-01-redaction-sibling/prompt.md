---
description: "PR #2 redacted --password=value; the space-separated --password value still leaks, against the README. Expect an open lead on that form, ideally reproduced."
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
tags: [inspector]
---

Use the inspector's inspect skill. Investigate PR #2 of the repository you are started in: what it fixed, which earlier change caused the bug, and whether the same bug is still anywhere in today's code.
Work at most 3 cases. Write the case file to docs/inspector/case.md, in English. Nobody can answer questions during this run: where you would ask, take the default. Change no other file.
