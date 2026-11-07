---
description: "Review PR #48 (branch pr48, 23 commits of review fixes) before it merges. Scored against the 8 bugs #50 later found in it (R1-R8)."
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Agent]
tags: [inspector, review]
---

Before I merge the branch pr48 into main: review it against this project's history. What in it could break something, or leaves a bug it meant to fix?
Write your findings to docs/inspector/case.md, in English. Nobody can answer questions during this run: where you would ask, take the default. Change no other file. Don't use the network.
