---
description: "Plan sanity: a feature touching accounts, passwords and data model must be sized large, with 3-8 tasks, tests inside tasks (not one last 'write tests' task) and password hashing in the design."
max_turns: 20
allowed_tools: [Read, Glob, Grep, Skill, Write]
tags: [factory, plan]
---

You are the factory's spec-writer; use the factory spec-writer skill.

Feature: add user accounts: sign-up and login with a password, stored in a local file, and a `--user NAME` option so each user has a separate cart.
Write the spec to .factory/spec.md (create the folder if needed).
End the spec file with a "## Code map" section, for the builder and reviewers to start from instead of searching again: each file the change touches or depends on, with the functions, types and line ranges that matter (path:start-end) and a few words on each; and the commands that test the change. In it, list every copy of the code the change touches (the same logic in another module, a bundled and a standalone version, generated output) and mark each in or out of scope.
Then judge the size of the feature, on a line of its own:
SIZE: small, medium or large
small: a local change in one or two files. medium: a few files in one area, the design clear. large: it spans several modules, or needs design decisions (architecture, data model or migrations, security, concurrency), or the request leaves real questions open.
Then end your answer with the task breakdown, in this exact form, 3 to 8 tasks, in any order:
TASKS:
1. [high] <short imperative title>
2. [medium] <title> (needs 1)
Priority is how much a task matters to the feature; "needs" lists the tasks it depends on.
Don't write implementation code; don't edit any file but the spec.
