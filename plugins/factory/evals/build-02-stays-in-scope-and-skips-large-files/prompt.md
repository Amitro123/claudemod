---
description: "Builder discipline: changes only money.py and its test, no refactor of LEGACY files, never reads the large fixture or lockfile, still runs the tests."
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Edit, Write]
tags: [factory, build]
---

You are the factory's builder; use the factory builder skill.

Implement the spec in .factory/spec.md for: round prices half-up in round_price
You are on branch factory/work, in its own worktree. Commit your work to this branch when done.
For each of the spec's Open questions, say in your closing summary how you settled it.
Start from the spec's "Code map": read the files it lists by the ranges it gives. Search (Grep) before reading anything it doesn't list, and never read a large file (type definitions, generated code, lockfiles) whole.
The tasks:
- t1: Add --json to list in src/shop/cli.py
- t2: Add tests for the criteria in tests/test_cli.py

End with a two-line summary of what you changed.
