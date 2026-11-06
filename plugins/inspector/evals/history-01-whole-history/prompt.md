---
description: "8 PRs: a fix-of-fix chain (#6 → #8) among features, and #4's escape fix that left a copy in another file (email_body). The prompt names no PR. Expect a lead on email_body, the chain named, email_subject (plain text) not a lead."
max_turns: 50
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
tags: [inspector]
---

This project has had a few bug fixes. Investigate its history and tell me what still needs fixing.
Work at most 4 cases. Write the case file to docs/inspector/case.md, in English. Nobody can answer questions during this run: where you would ask, take the default. Change no other file.
