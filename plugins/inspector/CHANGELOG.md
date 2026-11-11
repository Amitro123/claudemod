# Inspector changelog

## Unreleased

- Fixed: `evidence.py --unit` (and `--show`) with a sha prefix that matches more than one unit now exits 2 naming the candidates instead of silently using the first match; a full or unambiguous prefix works as before.
- Fixed: blame line counts now skip the same trivial lines as the copy detector (comment lines, bare `return`/`pass`/`break`), so a comment-only hunk no longer inflates the top `introduced_by` culprit or turns a change into a fix-of-fix. `BLAME_CACHE_VERSION` is v4, so older cache entries are not reused.
## 0.6.1 (2026-11-10)

- Fixed: a delegation or routing rule could hand the whole run to one worker, which cannot start agents, so the parallel recipe ran serially. SKILL.md and `references/parallel.md` now say the main conversation orchestrates and starts the readers, sweepers and verifiers itself; pinned by a test.
- Release-confidence tooling (maintainers only, nothing shipped in the skill): `tests/test_doc_commands.py` runs the commands the docs document (SKILL.md, references/, agents/) against a temporary workspace and fails if too few are found, with explicit multi-flag cases for `merge_cards`, `merge_verdicts`, `lint_leads`, `crosscheck` and `handoff`.
- Release-confidence tooling: `evals/scorecard.py` records per-version precision, recall on a gold file, duplicates and cost per verified lead, with an `--append` history and a `compare` mode (see `evals/README-scorecard.md`); maintainers only, not shipped in the skill.

## 0.6.0 (2026-11-10)

- Fixed: `merge_cards.py --sweep` and `merge_verdicts.py --verdicts` kept only the last occurrence when repeated, silently dropping earlier files; every occurrence is now honoured (also mixed with `--sweep a b`), and each file's lead count is printed to stderr. A missing sweep path still exits 2.
- `merge_cards.py`: leads in the same file whose line ranges intersect are flagged `possible_duplicate_of` each way even when the wording differs, and listed under "Possible duplicates (kept)" with the reason (`lines overlap` or `similar wording`); nothing is merged or dropped for it.
- `lint_leads.py` L9: a `verified` change that contains a query or command to run against data (`| where`, `| summarize`, `SELECT ... FROM`, Kusto, `az monitor log-analytics query`) with no probe naming a read-only run warns.
- `handoff.py`: a lead with `observed_in_production: yes` now sorts above a higher-level lead whose production state is unknown or `no` (then level, reach, verdict).
- Outside-in sweep: rendered output (HTML, e-mail, markdown, dashboard, chat message) is a sink class in questions 1 and 2 with an edge-payload probe, and a closing "Edge payloads" section: `reproduced` only if an edge payload was run, else `suspect`.
- Outside-in sweep: `references/outside-in.md` (eight questions: trust boundaries, context injection, secrets in logs, enforcement versus text, command construction, destructive writes, loss paths, packaging) and an `Outside-in mode` in the sweeper; the parallel recipe runs three sweepers (code, docs, outside-in).
- Fixed: case-reader and sweeper must write strict JSON (doubled backslashes) and validate the file; `merge_cards.py --repair-escapes` (opt-in) repairs invalid escapes in a card, logs it and keeps `<name>.orig`; default still refuses.
- Sweeper writes its JSON leads to `<tmp>/sweep-<k>.json` itself (tool `Write` added) and replies with the path and lead count; the merge step reads those files. Case-reader likewise writes its card to the path in its prompt (tool `Write` added) and replies with the card; no path means reply only.
- INS-02: `leadsio.py` is the one reader and validator for lint, handoff and crosscheck; `--cards merged.json` (a file) now works, errors name file and item path and exit 2 before any output is written.
- INS-06: `lint_leads.py` rejects malformed `complete` / `complete.siblings` with exit 2, also without `--strict`.
- INS-05: `merge_verdicts.py` exits 2 on duplicate lead `where` and on conflicting verdicts for one `where`.
- INS-01: `handoff.py` prints `verifier:` evidence and `would settle:`, and lists NOT REAL leads in a separate "Rejected by the verifier" section.
- Fixed: the blame cache is no longer used on a shallow repository, so `git fetch --unshallow` no longer leaves a stale attribution; BLAME_CACHE_VERSION v3.
- Fixed: cached GitHub PR data now expires after 7 days; new `--refresh-github` re-reads it (a failed read keeps the old entry); GH_CACHE_VERSION v2.
- Method rules: queries stay unverified until parsed or run read-only; production-noted failures sort first; log location, deploy order, dated exceptions, same-role siblings, allowlist counts, degrade-path failure modes.

## 0.5.0

Since 0.3.1:
- Collector: batched and cached blame, so a second run reuses saved evidence.
- Snapshots record provenance (schema, plugin fingerprint, repo, sha, options) and are validated on read.
- GitHub enrichment of PR bodies and labels in one GraphQL call.
- Precision fixes in fix detection (weak words, feature-first titles).
- Label rules: `security_actor`, reach conditions, `probe`, `test_kind`, `downstream`, `not_verified`.
- Producer trace and reconciliation checks for leads about data (references/producers.md, reconcile.md).
- Verify flow: a `verifier` agent re-checks leads in chunks of 8 with probes of its own, a
  `docs-checker` agent settles public-tool questions, `merge_verdicts.py` merges both into the
  leads before `handoff.py` (references/verify.md).
