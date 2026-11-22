# Spec: brain-hud `redact_secrets` gaps (issue #184)

## Problem

`redact_secrets` in brain-hud (`host_layout.py`) is the one redactor behind `safe_for_markdown`, which writes
commands, commit subjects and error lines into the tracked `MISTAKES.md` and into hook messages. Several secret
forms pass through unchanged (probe in the issue, plus the comment on it and the curl forms retro fixed in PR #193):

| # | Input (fake value `abcd1234efgh`) | Today |
|---|---|---|
| 1 | `aws configure set aws_secret_access_key abcd1234efgh` | leaks (keyword rule needs `=` or `:`) |
| 2 | `npm config set //registry.npmjs.org/:_authToken abcd1234efgh` | leaks (same) |
| 3 | `curl https://x?key=abcd1234efgh`, `...?sig=...` | leaks (`key`, `sig` are not in the keyword list) |
| 4 | `curl -u alice:"pa ss" https://x` | masked to the space, `ss"` stays |
| 5 | `{'Authorization': 'token <40-hex>'}` | leaks (`Authorization` is followed by a quote, rule 3 needs `authorization:`; `token` scheme has no prefix so no token rule fires) |
| 6 | `curl -u "alice:S3cr` (cut, no closing quote) | start of the password stays (curl rule needs both quotes) |
| 7 | `-u :PAT`, `-u key:`, `-ualice:pw`, `-u \"alice:pw\"` | mirror of retro #193 forms; today: `-u :PAT` leaks (user side must be non-empty), `-u key:` leaks (password side must be non-empty), `-ualice:pw` leaks (whitespace is required after `-u`), escaped quotes leak/partly leak |

Who: anyone running brain-hud; the harm is a credential committed to MISTAKES.md.

### Broken invariant (for the PR)

The redactor assumed "a secret is introduced by `keyword=` / `keyword:` / a flag followed by whitespace, and is
either one whitespace-free word or a fully quoted string". The reports show it false in four ways: the separator
can be a space after a *subcommand* (`config set NAME VALUE`), the keyword can be a query parameter named only
`key`/`sig`, the key itself can be quoted (`'Authorization':`), and the value's quoting can be partial, empty
on one side, attached to the flag, escaped, or cut off.

## Scope

In: rules in `_SECRETS` / `_VALUE` in `plugins/brain-hud/skills/mistake-brain/scripts/host_layout.py` and tests in
`plugins/brain-hud/tests/skill/scripts/test_host_layout.py` and `test_redaction_cases.py`.

Out of scope:
- retro (`plugins/retro/.../transcript.py`, `test_mask_secrets.py`), other plugins, the TS redactor
  `plugins/brain-hud/hooks/journal.ts` and the shared file `plugins/brain-hud/tests/redaction-cases.ts` (the TS
  side runs the same file, so adding a case there without fixing `journal.ts` turns `brain.test.tsx` red; new cases
  therefore live in a Python-only table). Follow-up: same gaps in `journal.ts`.
- retro's argument-list form (`ARGV_USER_RE`, `mask_data`): callers of `redact_secrets` pass shell command strings
  and short text (`draft_mistake_on_revert.py:140`, `draft_mistake_on_validation_failure.py:169-170`,
  `revert_stop_hook.py:165,224`), never a decoded argv list, so it does not apply here.
- Entropy-based detection, a general scanner, other issues.

## Design

All changes are in the `_SECRETS` list (it is applied in order; each regex is `re.sub`-ed). Keep every regex free of
nested unbounded quantifiers over overlapping classes (no quadratic backtracking on long colon- or quote-heavy lines;
retro hit this in #193).

1. **Subcommand form (cases 1, 2).** New rule: `(aws configure set | npm config set | npm set | yarn config set |
   pip config set)`, optionally one leading flag with its value (`--profile p`), then a NAME that contains
   `token|password|passwd|secret|key|auth` (case-insensitive, `\S*` around it so `//registry.npmjs.org/:_authToken`
   and `aws_secret_access_key` match), then whitespace, then a VALUE (`_VALUE`, not starting with `-`). Replace the VALUE
   with `[redacted]`, keep command and name. A name without such a keyword (`region`, `registry`) is untouched.
   Accepted over-redaction: `npm config set always-auth true` hides `true`.
2. **Query values (case 3).** New rule: `([?&](?:key|sig|signature|x-amz-signature))=[^\s&#"']+` (case-insensitive)
   -> `\1=[redacted]`. Requiring `?`/`&` before the name keeps prose `key=value` pairs, `?keyword=x` and words
   containing `key` unchanged (`key` must be the whole parameter name, then `=`).
3. **Quoted Authorization key (case 5).** Rule 3 (`authorization`) accepts an optional quote (possibly
   backslash-escaped) between the name and the colon and before the value: `authorization\\?["']?\s*:\s*\\?["']?`,
   then the existing optional scheme (`bearer|basic|token`), then the value up to whitespace or a quote.
4. **curl `-u` / `--user` (cases 4, 6, 7).** Rewrite rule 5 to the shape retro uses:
   - flag: `-u` followed by `\s*` (attached form allowed), or `--user` followed by `\s+` or `=`; still
     `(?<!\S)` before the flag so `git push -u origin` and `sudo -u bob` are untouched (a colon is required in the value);
   - value must contain a colon, and either side of it may be empty (`:PAT`, `key:`);
   - quoted value (`"` or `'`, optionally preceded by a backslash) is taken whole: `[^"\n]*:[^"\n]*`, closing quote
     optional so a cut-off value runs to the end of its line only (never across `\n`);
   - unquoted: user side `[^\s:"';|&)]*`, colon, password side that may contain a quote opening a quoted tail
     (`alice:"pa ss"` -> whole quoted string via `_VALUE` shape) and otherwise stops at whitespace or a shell
     separator (`;` `|` `&` `)`), so `curl -u a:pw;echo ok` keeps `echo ok`;
   - whether the closing quote is kept in the output follows retro's `mask()` (check it; either is acceptable as long as
     no part of the secret remains).
5. Rules 1, 2, 4-11 otherwise unchanged. `_DASH_P` untouched.

Failure modes: an unmatched shape stays unredacted (heuristic, documented in the module comment, which the builder
updates to list the new forms). Over-matching only ever replaces more text with `[redacted]`; the `keep` cases in
`redaction-cases.ts` (`git push -u origin main`, `sudo -u bob git checkout -- .`, etc.) must remain byte-identical.

## Acceptance criteria

Fake values only; "redacted" means the secret substring is absent from `redact_secrets(text)` (assert absence, not
equality with a template).

1. Each of these fails on `main` and passes after the fix: cases 1-6 above, exactly as written in the table
   (`aws configure set aws_secret_access_key abcd1234efgh`; `npm config set //registry.npmjs.org/:_authToken abcd1234efgh`;
   `curl https://x?key=abcd1234efgh`; `curl https://x?sig=abcd1234efgh`; `curl -u alice:"pa ss" https://x` with
   neither `pa ss`, `ss"` nor `pa` left; `{'Authorization': 'token ' + 40 hex}`; `curl -u "alice:S3cr`).
2. Retro #193 forms that apply are redacted: `curl -u :PAT https://x`, `curl -u key: https://x` (the key is the secret),
   `curl -ualice:pw https://x`, `curl -u \"alice:pw\" https://x` (backslash-escaped quotes), `curl --user="svc:pw"`.
3. Boundary cases, one table row each with its reason in the test file:
   - `?signature=`, `&sig=` after another param, `?Key=` upper case (other spellings/positions of the same input);
   - `aws configure set --profile p aws_secret_access_key abcd1234efgh` and `... aws_secret_access_key abcd1234efgh --profile p`
     (flag order); `aws configure set aws_session_token ...`;
   - `curl -u "alice:` cut right after the colon, `curl -u 'alice:S3cr` single-quoted cut, cut in the middle of a
     password containing a quote (empty/cut-off values); a cut-off value followed by `\n` + another line keeps the next line;
   - `curl -u a:pw;echo ok` keeps `echo ok`; `curl -u a:"p w" https://x` keeps `https://x`;
   - `'authorization': "Bearer <tok>"`, `\"Authorization\": \"token <hex>\"` (escaped JSON quoting of the same header);
   - Windows/other form: `-u` with `--user alice:pw` (long flag, space).
4. Must stay unchanged (`redact_secrets(x) == x`), each with a reason: `git push -u origin main`, `sudo -u bob ls`,
   `aws configure set region us-east-1`, `npm config set registry https://registry.npmjs.org/`, prose
   `press any key to continue`, `set key=value pairs`, `curl https://x?keyword=abc`, `git show 3f2a9c1`,
   `curl -u alice` (no colon, no secret).
5. Existing coverage still passes: `test_every_shared_secret_is_redacted`, `test_every_shared_plain_line_is_kept`
   (shared cases untouched), and retro's drift test `test_retro_mask_and_brain_hud_redact_agree_on_shared_probes`
   (read-only run, must still pass).
6. A redaction of a 50 000-character line made of repeated `-u a:` / `"` / `:` fragments finishes in under 2 seconds
   (no catastrophic backtracking).
7. The new tests live in `plugins/brain-hud/tests/skill/scripts/`, which `.github/workflows/skill.yml:18`
   (`python -m pytest plugins/brain-hud/tests/skill -q`) runs in CI. The PR shows the new tests failing on the
   pre-fix `host_layout.py` (command and output) and passing after. One end-to-end test goes through
   `safe_for_markdown` (cut at the length limit, the actual entry point), not only `redact_secrets`.

## Open questions

- Closing quote kept or dropped after a quoted credential: assumed "follow retro `mask()`" (keeps JSON text valid);
  either passes the criteria.
- Stale comment at `plugins/retro/tests/test_mask_secrets.py:147-148` ("brain-hud keeps a quoted `'Authorization'`")
  becomes false after this fix; retro is out of scope here, so list it as a follow-up in the PR (and add the probe to
  retro's shared `PROBES` there).
- `journal.ts` redact (TS side) has the same gaps; follow-up issue, not this PR.

## Code map

Files changed:
- `plugins/brain-hud/skills/mistake-brain/scripts/host_layout.py` — the fix. `_VALUE` :71, `_SECRETS` :72-93
  (rule 1 keyword `=`/`:` :76; rule 2 flag+space :77; Authorization :79; bearer/basic :80; curl -u :82; URL creds :88;
  cookie :90; redis -a :92), `_DASH_P` :95, `_dash_p` :98-100, `redact_secrets` :103-107 (applies `_SECRETS` in order,
  then `_DASH_P`), `safe_for_markdown` :110-113 (flatten newlines, redact, replace backticks, THEN truncate to `limit`).
- `plugins/brain-hud/tests/skill/scripts/test_redaction_cases.py` (21 lines) — add a Python-only table of redact/keep
  cases with reasons next to the shared-cases tests; it imports `redact_secrets` via `sys.path` to `skills/mistake-brain/scripts`
  and loads shared `tests/redaction-cases.ts` (JSON after `\nexport default `).
- `plugins/brain-hud/tests/skill/scripts/test_host_layout.py` — currently has no redaction tests (imports `host_layout`
  :21); add the `safe_for_markdown` cut-off test and the timing test here.

Read-only dependencies (do not edit):
- `plugins/brain-hud/tests/redaction-cases.ts` — shared redact/keep cases (also run by `brain.test.tsx:1035` against `journal.ts`). Keep cases include `git push -u origin main` :77, `sudo -u bob git checkout -- .` :78; redact cases include `curl -u alice:s3cretpass https://x` :28, `Authorization: token ghx0abc123secret` :24.
- `plugins/retro/skills/distill/scripts/transcript.py:453-519` — model to mirror: `AUTH_HEADER_RE` :471, `CURL_USER_RE` :472-474, `ARGV_USER_RE` :477 (not mirrored), `mask` :505.
- `plugins/retro/tests/test_mask_secrets.py:141-159` — drift test importing `host_layout.py` by path and running `PROBES`.
- Callers: `hooks/draft_mistake_on_revert.py:93,140`, `hooks/draft_mistake_on_validation_failure.py:169-170`, `hooks/revert_stop_hook.py:165,224` (all under `plugins/brain-hud/skills/mistake-brain/`); all pass strings.

Copies of the logic:
- `plugins/brain-hud/hooks/journal.ts` `redact` (TS twin) — OUT of scope (follow-up).
- `plugins/retro/skills/distill/scripts/transcript.py` `mask` — OUT (already fixed by #193, other plugin).
- `plugins/retro/skills/board/scripts/board.py`, `plugins/inspector/skills/audit/scripts/board.py` — contain `_SECRETS`/`redact_secrets`-like names; OUT (other plugins).
- `plugins/brain-hud/tests/redaction-cases.ts` — shared fixture, OUT (see Scope).

Commands (no `claude plugin test`; fails on Windows for environmental reasons, as does `test_plugin_fixes.py`):
- `python -m pytest plugins/brain-hud/tests/skill/scripts/test_redaction_cases.py plugins/brain-hud/tests/skill/scripts/test_host_layout.py -q`
- `python -m pytest plugins/brain-hud/tests/skill -q` (what CI runs)
- `python -m pytest plugins/retro/tests/test_mask_secrets.py -q` (drift check, read-only)
- Failing-first evidence: run the first command with the new tests on the unmodified `host_layout.py` and paste the output in the PR.
- Repo CLAUDE.md also asks for the inspector pre-merge check output as a PR comment and a row in `plugins/inspector/evals/premerge/README.md`; those belong to the PR step, not this change's code.

SIZE: medium

TASKS:
1. [high] Write the failing tests first: Python-only table of redact/keep cases with reasons plus the safe_for_markdown cut-off test, shown failing on the current code
2. [high] Rewrite the curl -u/--user rule in host_layout.py (empty sides, attached, escaped quotes, quoted-with-space, cut-off, separators) (needs 1)
3. [high] Allow a quoted Authorization key and token scheme in the Authorization rule (needs 1)
4. [high] Add the subcommand rule for aws configure set / npm config set secrets (needs 1)
5. [medium] Add the ?key= / ?sig= / signature query-value rule (needs 1)
6. [medium] Add keep-cases and the linear-time test; run brain-hud skill suite and retro drift test; update the module comment (needs 2, 3, 4, 5)
