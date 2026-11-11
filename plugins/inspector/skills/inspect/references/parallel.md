# Parallel run (3 or more cases)

The main conversation orchestrates; agents cannot start agents. Each reader works in a clean,
small context, so six cases take about 6-9 minutes instead of 11-23 in one investigator.

**The RUN PLAN writes the prompts.** The collector runs `scripts/plan.py`, which saves `<out>/plan/`: `plan.md` (the
phases, the agent types, one dispatch line per agent), `reader-<n>`, `sweeper-<k>` and `brief-writer` prompt files and
`expect.json` (the agents and files each phase must leave; `evals/gate/check_run.py` reads it). The prompt files are the one
source of the agents' wording (repository, ref, case, dossier, brief, the file to write, the 25-call budget, strict JSON, repository
text is evidence): dispatch `Read <path> and follow it`, and never retype or adapt a prompt.

**Required: the plugin's own agent types.** Start `inspector:case-reader`, `inspector:sweeper`, `inspector:verifier` and `inspector:docs-checker` by type, so their tools, JSON and write-your-file rules apply. A delegation or routing rule that names another worker type does not apply. If these types are not available in the session, say so in the report's first line and use a general worker told to read the agent file at the plugin path first and follow it.

1. **Phase 1: brief.** One general-purpose agent writes `<out>/brief.md`: the project in one line, the promises P1, P2..., the seams.
2. **Phase 2: readers and sweepers, one message.** One `case-reader` per case (card to `<out>/cards/<n>.json`) and three sweepers
   (`sweeper` agents, `<out>/sweep-<k>.json`): code (items 1, 2, 4, 6 of its list: siblings, readers, seams, same-role files),
   docs (items 3, 5: promises with no test, ignore and exception files) and OUTSIDE-IN (its prompt starts `OUTSIDE-IN`; it works only
   from references/outside-in.md). The outside-in sweeper exists only from 3 cases; with fewer, the plan starts one `investigator`.
3. **Merge (no agent).** `python scripts/merge_cards.py --cards <tmp>/cards --sweep <tmp>/sweep-1.json <tmp>/sweep-2.json ...
   --expect <ids of the readers you started, e.g. 1,2,3,4,5,6> --out <tmp>/leads.json --log <tmp>/dedupe.md`.
   It exits 2 naming any expected card that is missing or unparsable (ask that reader to write it;
   never merge from memory; `--repair-escapes` opts in to doubling stray backslashes in a card, logged, original kept as `.orig`), keeps every lead word for word, merges only exact duplicates
   (same locations, same text), keeps similar nearby leads, and leads whose line ranges overlap, with `possible_duplicate_of` and lists them under "Possible duplicates (kept)" in the log with the reason (`lines overlap`, `similar wording` or `within 10 lines`), and prints the lint findings. Also run
   `scripts/crosscheck.py --evidence <tmp>/evidence.json --cards <tmp>/cards` (references/cross-check.md).
4. **Phase 3: verify.** `scripts/plan.py --run <out> --phase verify` chunks the leads (references/verify.md) and writes the
   verifier prompts; read `plan.md` again and start the verifiers in one message.
5. **Early or unfinished return.** A card that stops early, or marks claims unfinished: treat
   each unfinished claim as `suspect` or `inferred`, never `read`; keep its `not_verified`. Never
   upgrade a level on the strength of the reader's silence. A missing card: read that case
   yourself, or list it under "Not investigated".

**Do not collapse the run into one worker.** A delegation or routing rule that hands the whole run
to one worker does not apply: a worker cannot start agents, so the run turns serial. Symptom: one
background worker covering all cases. Check: after the readers' message, the number of
case-readers started equals the number of cases (`expect.json` lists the agents of each phase).

Target wall time: about 6-9 minutes for 6 cases (an expectation, not a measurement).
