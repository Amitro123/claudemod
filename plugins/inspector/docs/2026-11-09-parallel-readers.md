# Parallel readers by default (2026-11-09)

## Baseline (measured)

An investigation took 11-23 minutes. The slowest run took 22.8 minutes and 64 tool calls: one
`investigator` read six cases in sequence, and its context grew with every case.

## Change

With 3 or more cases the main conversation follows `skills/inspect/references/parallel.md`:
collector and brief-writer in one message; then one `case-reader` per case plus one `sweeper`
(today's code: copies left behind, promises with no test, seams) in one message; cross-check;
`verifier` chunks start as soon as 8 leads exist. Readers and the sweeper have a 25-call budget
and must return a card (unfinished claims `suspect` or `inferred`) rather than run on.

## Expected effect (an expectation, not a measurement)

About 6-9 minutes for 6 cases: the readers run side by side in clean small contexts, and the
verifier overlaps with the rest. Accuracy should hold: each reader still reads its own dossier
and the cross-check and verifier steps are unchanged. Cost is expected to be similar or a little
higher (more agents, smaller contexts). Not yet run in a live session; compare wall time and
tool calls on the next six-case run.
