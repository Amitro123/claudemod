# Cross-check: the cards against the collector

Used when the work comes back (SKILL.md, step 3).

From an investigator: read its case file, then cross-check its leads against the collector as
below (pass its cases as cards if it listed them, or skip the cross-check) and check its reproduced
and read leads at their places before you report them. From case readers: each replies with its
card, as JSON. Then cross-check the readers against the collector,
the cards on stdin (`--cards` also takes a folder: the RUN PLAN runs it on `<out>/cards`). Reuse the saved evidence whenever available; this preserves the exact
ref and scope and avoids collecting the history again:

```bash
python3 "<skill_root>/scripts/crosscheck.py" --evidence "<out>/evidence.json" --cards - <<'CARDS'
[ <card 1>, <card 2>, ... ]
CARDS
```

Only when evidence could not be saved, use `--repo <repo> --ref <collected-sha>`
and the original `--unit`, `--path`, `--since`, `--max`, `--history`, custom `--component-root` values and blame limits.

If cross-check or handoff exits nonzero, correct the input or output-path problem before
continuing. Do not replace malformed or unreadable cards with an empty list. `[]` is valid only
when the investigation actually returned no cards or leads. "Both unknown" is not corroboration.

For each card it says whether the reader's culprit agrees with blame's. It says whether each
sibling the reader reports sits on a copy the collector found ("both") or not ("reader only").
It lists the copies left behind that no card decided. Your reading goes where they differ:

- a culprit that disagrees: read both diffs and settle it;
- a sibling the reader alone found at level `read`: read the code at its place before it becomes
  a lead (one at `reproduced` names its probe: check that the probe tests what it claims);
- a copy no card decided: check it, as in step 5.

A culprit both sources name is `blame` and `read` at once: say so on the card. The readers'
cards become the case file's cards, in the text form of SKILL.md step 3.
