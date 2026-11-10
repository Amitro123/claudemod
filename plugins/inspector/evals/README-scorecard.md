# Scorecard

`scorecard.py` turns one Inspector run into one row of numbers, so versions can be compared and a
regression shows up as a delta. Stdlib only. It is a maintainers' tool and is not shipped inside
the skill folder.

```bash
python plugins/inspector/evals/scorecard.py score --merged merged.json \
    [--gold gold.json] [--metrics metrics.json] [--append history.jsonl] [--label "<scope>"]
python plugins/inspector/evals/scorecard.py compare --history history.jsonl
```

`score` prints one JSON row and a short Markdown table; `--append` adds the row to a JSONL file.
`compare` prints the last two rows side by side with the deltas (exit 2 with fewer than two rows).

## Inputs

- `merged.json`: what `handoff.py` takes, a JSON array of leads with `verdict`, `category`, `reach`
  (the output of `merge_verdicts.py`). A lead with no verdict counts as `unverified`.
- Gold file (optional): a JSON list of items, the bugs a maintainer already knows the project has.
- Metrics file (optional): a report from the run-metrics skill, or just
  `{"cost_usd": 1.8, "requests": 240, "minutes": 35}`. The totals are found at any depth under
  `cost_usd`, `requests`, `minutes`.

## What the row holds

| Field | Meaning |
|---|---|
| `verdicts` | count per verdict: REAL, REAL-LOW, UNVERIFIABLE, unverified, NOT REAL |
| `precision` | (REAL + REAL-LOW) / (leads - UNVERIFIABLE); the UNVERIFIABLE count is shown next to it |
| `not_real` | leads the verifier rejected |
| `security` | leads labelled `security`, and how many of them the verifier kept (REAL or REAL-LOW) |
| `duplicate_clusters` | groups of leads linked by `possible_duplicate_of` |
| `gold` | recall, the covered items with the lead that covered each, the uncovered items |
| `cost` | cost, requests, minutes and cost per verified lead (cost / (REAL + REAL-LOW)) |
| `version` | read from `plugins/inspector/.claude-plugin/plugin.json` |

Precision is a rate over what the verifier could decide, not over everything found: read it with
the UNVERIFIABLE count beside it. A lead the verifier rejected (NOT REAL) never covers a gold item.

## Gold file format

A gold file for a real project must live OUTSIDE this repository: it names real defects. Keep it
next to that project, and pass its path on the command line. Synthetic example:

```json
[
  {"id": "G1", "title": "retry counter never resets", "severity": "high",
   "paths_any": ["src/uploader", "uploader.py"], "words_any": ["retry", "counter"]},
  {"id": "G2", "title": "settings file rewritten on parse error",
   "paths_any": ["config/"], "words_any": ["rewrite", "overwrite"]}
]
```

An item is covered when at least one lead matches one of its `paths_any` substrings (against the
lead's `where`) AND one of its `words_any` keywords (against the lead's `what`, `breaks`, `change`,
`test`), case-insensitive, and the same lead satisfies both. `severity` is optional and only echoed.

## Comparing versions

Score every run of a fixed project with the same gold file and the same `--append` history, then
`compare`. A drop in recall, in precision, or a rise in cost per verified lead between two versions
is the signal; one row alone says little.
