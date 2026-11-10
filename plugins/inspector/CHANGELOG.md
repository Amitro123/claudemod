# Inspector changelog

## Unreleased

- Fixed: case-reader and sweeper must write strict JSON (doubled backslashes) and validate the file; `merge_cards.py --repair-escapes` (opt-in) repairs invalid escapes in a card, logs it and keeps `<name>.orig`; default still refuses.
- Sweeper writes its JSON leads to `<tmp>/sweep-<k>.json` itself (tool `Write` added) and replies with the path and lead count; the merge step reads those files. Case-reader likewise writes its card to the path in its prompt (tool `Write` added) and replies with the card; no path means reply only.
- INS-02: `leadsio.py` is the one reader and validator for lint, handoff and crosscheck; `--cards merged.json` (a file) now works, errors name file and item path and exit 2 before any output is written.
- INS-06: `lint_leads.py` rejects malformed `complete` / `complete.siblings` with exit 2, also without `--strict`.
- INS-05: `merge_verdicts.py` exits 2 on duplicate lead `where` and on conflicting verdicts for one `where`.
- INS-01: `handoff.py` prints `verifier:` evidence and `would settle:`, and lists NOT REAL leads in a separate "Rejected by the verifier" section.
- Fixed: the blame cache is no longer used on a shallow repository, so `git fetch --unshallow` no longer leaves a stale attribution; BLAME_CACHE_VERSION v3.
- Fixed: cached GitHub PR data now expires after 7 days; new `--refresh-github` re-reads it (a failed read keeps the old entry); GH_CACHE_VERSION v2.
- Method rules: queries stay unverified until parsed or run read-only; production-noted failures sort first; log location, deploy order, dated exceptions, same-role siblings, allowlist counts, degrade-path failure modes.

## 0.5.0 (candidate, not published)

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
