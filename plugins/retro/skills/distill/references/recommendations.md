# Recommendations: the shape

One block per lesson, most severe first. `lint_skill.py --recommendations FILE` checks it.

```
## R1: <what went wrong, in a few words>
- Destination: check | test | access | guidance | skill | model | no-change
- Observed: <the failure, as the transcript shows it> (evidence: <step or call numbers from the digest, a file:line, a command's output>)
- Measured: <counts from the digest or the agent audit: calls, failures, retries; "none" when nothing was counted>
- Existing: <the checks, CI, docs or briefs you read for this, and what they show>
- Change: <what to change> -> <the file or component it goes in>
- Why: <why that change addresses the failure: a hypothesis, said as one>
- Verify: <how its effect would show: a test that fails before and passes after, the next run's count of the same calls, the run-log row to compare>
```

Rules for the fields:

- **Observed** needs evidence a reader can find: a step number, a call, a file and line, not "it seemed".
- **Measured** is what was counted, nothing more. A claim that something got better (fewer calls, faster) names
  what it is compared with: "12 calls, against 30 in the run of 2026-11-02 (run-log row 3)".
- **Existing** is filled in for every destination: you looked before proposing.
- **no-change** has `Change: none` and says under Verify what evidence would settle it (another run, a log).
- **skill** points at the draft: `Change: steps 2-4 -> <scratch>/distill/<name>/SKILL.md`.
