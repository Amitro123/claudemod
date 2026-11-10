# Merge without a model agent (2026-11-10)

Baseline (parallel runs on a six-case history): about 9 minutes to leads, 12-13 with verification.
The single sweeper took 239 s, longer than any reader (62-152 s). The card-and-sweeper merge was a
model agent: about 1-2 minutes and 60-120k tokens per run, and in one run it silently skipped a
reader whose card file had not been written.

What changed:
- `scripts/merge_cards.py` does the merge deterministically (reads with `leadsio`, prints the
  `lint_leads` findings). `--expect <ids>` makes a missing or unparsable card exit 2 before anything
  is written. Leads are kept field for field; only `found_by`, `also_found_by`, `merged_from` are added.
- Dedupe is strict on purpose: same file, lines within 10, and word similarity (Jaccard, words of 4+
  letters) of at least 0.5. Near misses go to the log as possible duplicates for a person to decide.
- `references/parallel.md`: step 3 runs the script (no merge agent); the sweep is split in two
  `sweeper` agents when hotspots lie in two or more top-level areas; a `verifier` starts for the
  readers' leads while the sweepers still run.

Local regression on one real run (22 raw leads; the model merged 5 pairs to 17): the script merged
none and logged 19 possible duplicates, including all 5 pairs the model merged (similarity 0.14-0.44:
the readers worded one defect differently). The strict rule trades fewer merges for no wrong merges.
The threshold was not tuned to match.

Expected effect (an expectation, not a measurement): 1-2 minutes less on the critical path and no
merge tokens; a two-way sweep might cut the 239 s sweeper roughly in half; verifying early overlaps
verification with the sweep. Together about 6-7 minutes to leads. Not yet run in a live orchestration.
Expect a few more leads to reach the verifier than before; the log lists what to merge by hand.
