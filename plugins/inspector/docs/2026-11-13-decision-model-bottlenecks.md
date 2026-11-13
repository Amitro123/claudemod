# Where a decision model could cut wall time (2026-11-13, a plan, not a measurement)

## What we know

- **decision-fix** (`evals/decision-fix`): Gemini Decision 1 through OpenRouter answered 76 yes/no
  questions in one request, 1.8 s, $0.004, and tied the regex on the 36 labeled units (precision
  1.00, recall 0.88) once the question said review fixes after merge count. It replaces a step that
  is already instant, so it saves no time there. What it shows: a judgement over short text, in
  bulk, in seconds.
- **Time today** (the docs' numbers; none measured end to end since the last changes):
  - parallel-readers.md, measured: one investigator, 11-23 minutes.
  - merge-cards.md, measured on six cases: about 9 minutes to leads, 12-13 with verification. The
    single sweeper took 239 s, longer than any reader (62-152 s).
  - merge-cards.md, expected: with the script merge and two sweepers, 6-7 minutes to leads. Not
    run live.
  - verify.md: about 100k tokens per 11 leads; chunks of 8, one verifier each, at most 4 per message.
- **The critical path is agents reading code**: the slowest sweeper or reader, then the verifiers.
  The scripts (collector, merge, cross-check, handoff) are seconds.

A decision model cannot read code, run probes or search the repository. It can answer yes/no about
text it is handed, fast. So it saves time only where it **shrinks what an agent must read or
check**, or **replaces a judgement the main conversation makes by reading**. Ground rule 1 holds
throughout: its answer is evidence of nothing; it may order, filter or flag work, never set a
lead's level.

## Step 0: measure before changing anything

No end-to-end time has been measured since the merge script and the two sweepers. Without that
the bottleneck is a guess.

- Run one live parallel inspection (7+ cases) on a real repository.
- Phase times come from the run folder at no cost: `python evals/gate/timeline.py --run <out>`
  (`--json` for machine output). It reads `plan/expect.json` for the phases, agents and files, stats
  `evidence.json`, `brief.md`, each `cards/<n>.json`, `sweep-<k>.json`, `leads.json`, `dedupe.md`,
  `plan/chunk-<k>.json`, `verdicts-<k>.json`, `merged.json`, `open-bugs.md`, and prints per phase
  start, end and duration, per agent its file's time from the phase start, the critical path (the
  slowest agent of each phase) and any planned file that is missing (exit 1). Limit: an mtime is the
  last write, so a card shows when its reader finished it; the stub's first write is lost.
- Record tool calls per agent from the transcripts, and how many of each agent's calls went to
  each kind of work (dossier, copies left behind, siblings, probes).

Decide the candidates below by what that run shows, not by this list's order.

## Candidates, by expected gain

### A. Fewer leads into verification: duplicate pairs (expected: 1-3 minutes)

merge_cards.py keeps near duplicates and logs them ("Possible duplicates (kept)"). One real run:
22 raw leads, 19 possible duplicates logged, 5 pairs a model had merged; the strict rule merges
none of them. Every kept duplicate goes to a verifier: 22 leads is 3 chunks, 17 would be 3 too,
but on bigger runs each 8 leads saved is one verifier (about 70k tokens) and, past 4 chunks, a
whole wave.

- Ask, per logged pair: "Do these two leads describe the same defect at the same place?" with
  both leads' `where`, `what`, `impact`. One request for all pairs.
- Use: merge a pair only when p >= a high cut (0.9), keep both originals in `merged_from`, log
  the probability. Below the cut nothing changes.
- Measure: the 19 logged pairs of that run, labeled by hand (the 5 the model merged are known).
  Target: the 5 merged, no wrong merge. Cost: cents.
- Risk: a wrong merge loses a lead. Mitigation: the high cut, and the verifier still sees the
  kept lead's `merged_from`.

### B. Copies left behind, triaged before the sweep (expected: part of the 239 s sweeper)

The collector's copies left behind are "hints, not leads. Most are an idiom that happens to
repeat". The code sweeper (item 1) and each reader (step 4) spend calls deciding each one.

- Ask, per copy: "Given the fix's diff and this line with its surrounding lines, is this the same
  bug the fix repaired, left unfixed?" The collector already has the fix diff and the copy's place;
  it would add a few lines of context per copy.
- Use: order the copies by probability in the dossier and the sweeper prompt, and mark the low
  ones "likely idiom". Do not drop any: a reader may still check them, it just starts with the
  likely ones.
- Measure: the copies of the 16 labeled fixes in this repository; label each by hand (missed copy
  or idiom). Then a live run: sweeper tool calls and time with and without the order.
- Risk: low. Ordering never hides a copy.

### C. The fix verdict, as the triage step (expected: under a minute; better cases)

Step 2 of SKILL.md tells the main conversation to read every unit's title and correct the
regex's verdict. decision-fix showed the model makes this call as well as the regex, and catches
bump-only fixes the regex misses by design.

- Use: run the regex and the model; the units where they disagree are the only ones the main
  conversation reads. On this repository that is 2 of 76.
- Measure: labels after #72 (still owed by decision-fix), then a live run.
- Gain is small in time, larger in which cases get worked: a missed fix is a case never read.

### D. Culprit disagreements in the cross-check (expected: small)

crosscheck.py flags a culprit where reader and blame disagree; the main conversation reads both
diffs. A model could rank which disagreements most need it. Only worth doing if step 0 shows
these take real time.

## Not candidates

- **The verifier.** It runs probes and reads code at the ref; its value is that it did not write
  the leads. A model's yes/no is not a check (ground rule 1).
- **The docs-checker.** Its answers come from official docs on the web; a decision model has no
  sources to cite.
- **Readers and sweepers themselves.** They read code; the model can only shorten their list.

## Order of work

1. Step 0: one live run, `timeline.py`, the real phase times.
2. A and B offline on labeled pairs and copies (cents, minutes). Keep what meets its target.
3. One live run with the kept ones, compared with step 0 on the same repository and ref.
4. C once labels after #72 exist.

Each change ships behind a flag, off by default, until a live run shows the gain.
