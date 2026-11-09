# Integration review: external patch 0.3.1 on the faster collector (2026-11)

Source: `inspector-improvements.patch` (written by another model against `9ad8d84`), integrated on
`integrate/gpt-inspector-patch`, cut from `perf/inspector-collector` (`a89e2dd`). Its own claims
("verified", "78 tests pass") were not trusted; every row below was checked against the code and tests here.

## Decisions

| Change | Verdict | Reason |
|---|---|---|
| README / efficiency-review / evals text | ACCEPT | Matches the code; the review's measured numbers (17 s, 62 tests) describe the old collector and are historical. |
| plugin version 0.3.0 -> 0.3.1 | ACCEPT | Not bumped further. |
| `run-offline.sh` fails if either check fails | ACCEPT | Tested with stub commands. `claude plugin validate` passes here; the full script was not run (the pytest part takes many minutes on this machine). |
| `snapshot.py` provenance (schema, fingerprint, repo, SHA, options) | MODIFY | Options now also record the effective `excludes` (they change results); `metadata` and `workspace_warnings` take values the collector already has (toplevel, HEAD). |
| Fingerprint rejects any plugin edit | MODIFY | Too strict while developing the plugin. `INSPECTOR_ALLOW_PLUGIN_CHANGE=1` turns it into a warning (small, tested, in SKILL.md). Default stays strict. |
| `doctor.py` | ACCEPT | Read-only content comparison; says it cannot see the loaded copy. |
| `evidence.py`: ref resolved to SHA | MODIFY | Resolution and HEAD in one git call. Original name kept as `ref_requested` (shown in the summary header). A ref starting with `-` is refused. `ref` is now the SHA. |
| `evidence.py`: atomic `write()` | ACCEPT | Note: the temp file is created 0600, so the final mode is 0600 on POSIX (was umask-based). Harmless inside `.git`; unverified on POSIX here. |
| `evidence.py`: `--show` validates, `--repo` default | ACCEPT | Tested (moved clone, invalid JSON). |
| dossier `git show --first-parent` (root commit) | ACCEPT | Test added by the patch passes. |
| fallback dossier command pinned and shell-quoted | ACCEPT | `shlex.join` quotes a Windows path for bash only. |
| `crosscheck.same_unit` | MODIFY | PR ids exact, good (card #12 vs blame #1 now disagrees). Defect: any all-digit string was a PR id, so an all-digit commit prefix such as `1234567` never matched its SHA (about 4% of 7-char prefixes). Now numeric means a PR id only below 7 digits, the same rule as `evidence.py --unit`. |
| Copy decisions scoped | ACCEPT | `decided` is keyed `(unit, commit12, line, location)` and matches `left_behind` entries (`commit` is the 12-char SHA). The old "decided once any place checked" behavior is dropped on purpose; the old test assertions were rewritten. |
| Commit with no blame no longer inherits; ambiguous commit reported | ACCEPT | Tests pass. |
| "both unknown" counted apart | ACCEPT | |
| Exit codes: crosscheck/handoff 2 on invalid cards, 1 on write failure | MODIFY | Defect: on write failure the report was not printed at all, losing the only copy. Both scripts now print it and then exit 1. Callers: only SKILL.md invokes the scripts (agents do not) and it was updated. |
| Cards/dirs malformed fail before writing | ACCEPT | |
| `import snapshot` at top | MODIFY | Worked as a script (script dir is `sys.path[0]`) and in tests, but failed under `python -I` (`evidence.py`, `crosscheck.py`, `doctor.py`). Each now inserts its own folder first; test runs all four scripts with `-I` from another directory. |
| `workspace_warnings` git calls | ACCEPT | One extra `git status` (HEAD comes from the existing call). Measured 1.1 s on the keshet-claude-skills run while the machine was loaded; `--untracked-files=normal` can be slow on a huge tree. These calls bypass `Timing`, so `--timing` does not count them. The "HEAD differs" warning fires for any `--ref` other than HEAD (for example `origin/main`); accurate, but noisy. |
| New tests | ACCEPT / MODIFY | Windows fixes (path separators, read-only `.git` objects). `test_snapshot.py` rebuilt: pure tests use fake evidence (no repo); the rest share one repo and one collector run per module and are marked `slow`. |

## Equality (g)

`evidence.json` gains `snapshot`, `ref_requested`, and workspace entries in `warnings`; `ref` is now the SHA.
`tests/normalize.py` blanks only `snapshot.plugin.{path,fingerprint,version}`, the summary's two plugin
lines, and platform quoting of paths; schema, repository and every option stay compared. The golden was
regenerated and diffed against the old one: only `ref`, `ref_requested`, `snapshot`, the plugin lines and the
fallback command (now SHA-pinned) differ; units, fixes, culprits, copies, hotspots and case dossiers are identical.
A real-repo run matches the perf-branch baseline (`perf-after2`) and a same-minute run of `a89e2dd` on every
field except those.

## Precision fixes (branch `fix/inspector-precision`)

Four flaws seen in the model-router run (`keshet-claude-skills`, `--path mods/model-router`):

1. **A patch version bump is no fix signal.** It stays in `version_bumps` as a fact, but a unit is a fix only on
   words (title, or most commit subjects). PRs 113 and 123 were bump-only. Cost: hand-labeled fixes with nothing
   but a bump (#18, #25 of this repo) are no longer detected; the golden labels say so (`BUMP_ONLY_FIXES`).
2. **Removal units.** Code deletions >= `REMOVAL_RATIO` (4x) the additions and >= `REMOVAL_MIN_DELETED` (20 lines)
   give `verdict: "removal"` (tag `removal`) and no blame: `introduced_by` is empty, no fix-of-fix, no copies.
3. **Copies left behind** no longer count matches on import/require/from lines, comment lines, or
   `description:` / `when_to_use:` strings. They are listed under `ignored_matches` (top level and per commit;
   present only when non-empty) so nothing is dropped silently.
4. **`--path` is repeatable** (`--path a/ --path b/` = union). One `--path` is recorded as before (a string); several
   as a list, in `snapshot.options.path`, `path` and the markdown header. Validation compares the set, not the order.
   `crosscheck.py --path` repeats the same way.

Re-run on the same window (`--ref origin/main` e86fa2c, `--max 25 --history 80`, cold cache, 17.8 s): fixes 4 -> 2
(#105, #100 stay); #113 -> removal, no culprits (was 10 units blamed); #123 no longer a fix; fix-of-fix #105 only;
left-behind 5 -> 2 (two went with #123, one import line moved to `ignored_matches`); no unit appeared.

