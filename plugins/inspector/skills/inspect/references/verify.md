# Verify: the flow after the case file exists

The investigator and the case-readers find leads; they also grade their own work. This flow adds
two checkers that did not write the leads. Run it before the leads go to anyone who will act.

1. **Chunk.** Take the open leads as a JSON array (the investigator's block, or the cards'
   `complete.siblings`). Split them into chunks of at most 8, keeping `where` exactly as written.
2. **Verify, in parallel.** Start one `verifier` per chunk. Give each the repository path, the ref
   the case file names (`Investigated through <sha>`), the case file, its chunk's `where` values
   and a file to write, for example `<tmp>/verdicts-1.json`. Cost: about 100k tokens per 11
   leads. It is the most useful money in the run: it catches downgraded and mislabelled leads.
3. **Public-tool doubts, once.** Collect the leads flagged `needs_host_check` whose doubt is about
   how a public tool is documented to behave (a variable format, a query function, a file
   syntax). Start one `docs-checker` with one precise question per lead (the lead's
   `needs_host_check` text says what would confirm it). Pass its answers to the verifier's
   `unverifiable` entries by hand, or re-run the affected verifier with the answers. A doubt
   about your own deployment or data is not a docs question; leave it `UNVERIFIABLE`.
4. **Merge.**

```bash
python3 "<skill_root>/scripts/merge_verdicts.py" --leads leads.json \
  --verdicts verdicts-1.json verdicts-2.json --out merged.json [--drop-not-real]
```

   Each lead gains `verdict`, `verified_by`, `false_claims`; corrected labels replace the
   lead's, with `original_category` / `original_reach` kept; `not_verified` grows by what the
   verifier could not settle. A lead with no verdict is `unverified`. Exit 2 means a verdict names
   a `where` that is not in the leads, or a file is not a JSON array: fix it, do not merge around it.
5. **Hand off.** Run `python3 "<skill_root>/scripts/handoff.py" --cards merged.json --out open-bugs.md`
   (`--cards` takes a .json file, a folder of *.json, or `-` for stdin; `lint_leads.py` and
   `crosscheck.py` read the same way, and malformed JSON structure exits 2 before any file is written). Leads with verdict `NOT REAL`
   are not handed off (drop them with `--drop-not-real`, or `--drop` each one). `UNVERIFIABLE`
   leads are handed off marked as such, with what would settle them. `REAL-LOW` goes with its
   corrected labels.

## What it is not

The verifier reads code at the ref and runs probes on copies. It never replaces production
evidence: a lead about data, a pipeline or a deployed service still needs the check in
references/reconcile.md. Its verdict is a stronger reading, not an observation of production.
