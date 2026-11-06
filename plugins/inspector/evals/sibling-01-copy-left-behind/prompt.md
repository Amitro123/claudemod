---
description: "PR #2 quoted item titles in the CLAUDE.md export only; to_docs still writes them raw, against the README's promise. Expect an open lead on to_docs; to_csv is not a bug."
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
tags: [inspector]
---

Investigate PR #2 of the repository you are started in: what it fixed, which earlier change caused the bug, and whether the same bug is still anywhere in today's code.
Work at most 3 cases. Write the case file to docs/inspector/case.md, in English. Nobody can answer questions during this run: where you would ask, take the default. Change no other file.
