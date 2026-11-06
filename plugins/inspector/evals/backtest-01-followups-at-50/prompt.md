---
description: "Backtest on the real repository at #50, scoped to plugins/followups with a budget of 4 cases. Scored against the 13 followups bugs that #51-#72 fixed. Measures what the skill adds on a real history."
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
tags: [inspector, backtest]
---

Investigate the history of plugins/followups in the repository you are started in, and tell me what still needs fixing in it.
Work at most 4 cases. Write the case file to docs/inspector/case.md, in English. Nobody can answer questions during this run: where you would ask, take the default. Change no other file. Don't use the network.
