# PR body: the sections

The shape of PRs #201, #202, #203 and #205. Each section is evidence a reviewer can rerun.

```
Closes #<n>

## The broken invariant
<what the code promised, what the issue shows; siblings the sweep found beyond the issue>

## The change
<the helper or rule, where it lives, every caller that now uses it; what is deliberately unchanged>

## Regression test, failing first
`<test file>` (runs in `<workflow>`). On `main` (<sha>): **<n> failed, <m> passed**, the failing rows named.
After, on <sha>: <n> passed; `plugins/inspector/tests` <count>; `plugins/retro/tests` <count>.

## Boundary cases, each with a reason
| Row | Expected | Why |
The table covers these shapes, not every variant.

## Run on real input
<the command, before and after; or why the run could not tell them apart>

## Not checked
<each item, or where it is tracked>

## Pre-merge check
Its output, run on <sha>, is posted unchanged as a comment; the row is in `plugins/inspector/evals/premerge/README.md`.
A push after a review makes it a review of the older commit: the review comment names both.
```

End with the PR attribution line the session gives, without a session link.
