# Case file template

Keep the sections and their order. Write "none" in a section with nothing in it; don't drop it.
Every claim carries its level: **[reproduced]**, **[read]**, **[blame]** or **[inferred]**
(ground rule 1 of SKILL.md).

```markdown
# Case file: <project>, <scope>

<date> · <U> units read · <F> fixes (corrected count) · <W> cases worked in depth · <I> from titles only

## Verdict

3-5 sentences: what kind of project this is, the classes of bug that dominate among the worked
cases, the seam that breaks most, and what is still open.

## The brief

What the project promises, as a list, each with its component and source. The seams.

## The pattern board

| Class | Worked | From titles | Components | Example |
|---|---|---|---|---|

| Seam | Cases | Through what |
|---|---|---|

Then one short paragraph per real pattern (2+ cases): the cases, the shared cause, what each fix
assumed. Chains as `#A → #B → #C` with what each link assumed.

## Hotspots

The code files fixes return to, and why (one line each).

## Cases

The case cards, largest pattern first; within a pattern, oldest first. The cards worked from
titles only go last, one line each.

## Open leads

| # | Level | Where | What breaks | Impact (its own level) | Breaks (promise or sibling of) | Class | Seam | The change it needs | Test that proves it |
|---|---|---|---|---|---|---|---|---|---|

Level: reproduced | read | suspect; add `[needs-host-check]` when the impact depends on host
behaviour nobody observed (its impact level is then `unverified`). Category `security` needs a documented or code-traced path from an input an outsider or another system controls to a sensitive sink (a secret persisted or sent on, a guard bypassed, injection); it is `traced` even when the real-world trigger was not observed. Name the input, the boundary and the sink, one line each; a lead that cannot is not security. `needs-host-check` says what would confirm the trigger and never changes the category. Otherwise `broken-flow`, `cost` or `other`.
Each lead also carries `change_status` `verified` | `unverified`: `unverified` when the change depends on host or tool semantics nobody observed (a variable format that doubles quotes the query already adds); the change line then says what to verify first. `reach` `default-on` | `opt-in` | `unknown`, plus a short text (`trigger: none, flag defaults off`). Ranked as SKILL.md step 5 says: a broken promise a user hits,
then a seam with a fix-of-fix history, then the rest; reproduced first within each. A row with no
promise and no sibling in Breaks belongs under Recommendations, not here.

### Checked and clear

One line each: what was checked, and how it is handled.

## Recommendations

- A regression test per seam that broke twice.
- A rule for CLAUDE.md / .claude/rules/ per class that recurred 3+ times: the rule, the cases
  behind it.
- Process: where fixes keep missing copies or tests, what check would catch it.

## Not investigated

What you skipped and why: the units past the budget (by label, so a later run can scope to them), the collector's Warnings (shallow,
truncated), no host access, binary files.

Investigated through <sha>
```
