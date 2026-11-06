# Case file template

Keep the sections and their order. Cut a section's body to "none" rather than drop it. Every
claim carries its evidence marker: **[confirmed]**, **[blame]** or **[inferred]**.

```markdown
# Case file: <project>, <scope>

<date> · <N> units read, <F> fixes, <W> worked in depth, <I> from messages only

## Verdict

3-5 sentences: what kind of project this is, the classes of bug that dominate, the seam that
breaks most, and what is still open.

## The brief

What the project promises, as a list, each with its component. The seams.

## The pattern board

| Class | Cases | Components | Example |
|---|---|---|---|

Then one short paragraph per real pattern (2+ cases): the cases, the shared cause, what each
fix assumed. Chains as `#A → #B → #C` with what each link assumed.

## Hotspots

The files fixes return to, and why (one line each).

## Cases

The case cards, newest pattern first. Cards for units worked from messages only go last, short.

## Open leads

| # | Status | Where | What breaks | Class | The change it needs | Test that proves it |
|---|---|---|---|---|---|---|

Status: confirmed | suspect. Ranked: a broken promise a user hits first.

## Recommendations

- Regression tests, one per seam that broke twice.
- Rules for CLAUDE.md / .claude/rules/ for each class that recurred 3+ times (the rule, the cases
  behind it).
- Process: where fixes keep missing copies or tests, what check would catch it.

## Not investigated

What you skipped and why (budget, no access to PR comments, shallow history, binary files).

Investigated through <sha>
```
