# Verify flow (2026-11-09)

## Why

In five evaluations, the step that made the leads trustworthy was an independent skeptic that
re-checked every lead with probes of its own: about 60 leads, none wrong, and many downgraded or
mislabelled ones caught. A docs-checker with web access settled questions about public tool
behaviour (a Grafana variable format, a Kusto function, a Trivy file syntax) in about 30 seconds.
Both were run by hand; this release makes them part of the product.

## The flow

Described in `skills/inspect/references/verify.md`. After the case file exists:

1. Split the open leads into chunks of at most 8.
2. One `verifier` agent per chunk, in parallel. Cost: about 100k tokens per 11 leads.
3. One `docs-checker` agent for the leads flagged `needs_host_check` whose doubt is about a
   public tool's documented behaviour.
4. `scripts/merge_verdicts.py` merges the verdicts into the leads by `where`.
5. `handoff.py` runs on the merged array. `NOT REAL` leads are not handed off; `UNVERIFIABLE`
   leads are handed off marked as such.

`handoff.py` prints what the merge adds: `[verdict: X]` after the production marker (`unverified`
when absent), `false claims:` and `relabelled: category|reach old -> new` under the impact, a
`Verified: ...` header line when any lead has a verdict, and sorts REAL, REAL-LOW, UNVERIFIABLE,
unverified after the existing keys at equal level. `NOT REAL` leads are printed, not dropped.

## Verdicts

`REAL`, `REAL-LOW`, `NOT REAL`, `UNVERIFIABLE`. The verifier also corrects the labels (category,
reach, test_kind); the merge keeps the original category and reach beside the corrected ones.

## Limits

- The verifier reads code at the ref and probes copies; it never replaces production evidence
  (see `references/reconcile.md`).
- The docs-checker answers only from official documentation and says when a page does not answer.
- The two agents were written from the hand-run process and have not yet been run in a live host.
  `merge_verdicts.py` is covered by fast tests; the agents' behaviour is not.
