# Inspector changelog

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
