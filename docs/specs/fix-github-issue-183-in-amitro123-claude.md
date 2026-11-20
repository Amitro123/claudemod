# Spec: retro mask() misses ghu_/ghs_/ghr_ tokens, Authorization headers and curl -u (issue #183, P21)

## Problem

Retro's `mask()` is default-on and is what keeps secrets out of digests that go into skills (promise P21: a secret
in a transcript never reaches the digest). `TOKEN_RE` covers only `ghp_` and `gho_` GitHub tokens. `ghu_`, `ghs_`,
`ghr_` tokens, `Authorization:` headers (any scheme) and `curl -u user:pass` / `--user` pass through unchanged. The
brain-hud masker (`redact_secrets`) already catches all of them, so the two maskers have drifted.

Broken invariant: "TOKEN_RE and the Bearer rule cover the credential shapes a transcript contains." In fact the
list is hand-kept and was written for two GitHub prefixes and a Bearer scheme only; a prefix list, a scheme list and
a flag form were each assumed complete.

## Scope

- In `plugins/retro/skills/distill/scripts/transcript.py`: widen `TOKEN_RE` to `gh[pousr]_`, add an Authorization
  header rule and a `curl -u` / `--user` rule, and call them from `mask()`.
- Tests proving each form masked, in both digest formats (Markdown via `T.mask(render(d))`, JSON via
  `T.mask_data(d)`), plus a drift test against brain-hud.

### Out of scope
- Private-key blocks and Azure DevOps PAT shapes (#165; already present in this file, do not touch).
- brain-hud's own `redact_secrets` gaps; any change to `host_layout.py`.
- Any change to what retro collects; other issues (#184-#186).

## Design

Decision on reuse (issue says "prefer"): do NOT import `_SECRETS` from `host_layout.py` at run time. Retro and
brain-hud are separate plugins installed to separate cache directories; retro would break, or silently stop masking,
when brain-hud is absent. Instead retro keeps its own patterns (same shapes as `_SECRETS`) and a test in the retro
suite loads `host_layout.py` by path and asserts both maskers hide the same probe set, so they cannot drift
unnoticed. Assumed default; see Open questions.

Changes in `transcript.py` (near line 455-457, and `mask()` at 480-491):
1. `TOKEN_RE`: replace `ghp_...|gho_...` with `gh[pousr]_[A-Za-z0-9]{20,}`. Name and group shape unchanged
   (`lint_skill.py` uses `T.TOKEN_RE`, so linting gains the same coverage).
2. New `AUTH_HEADER_RE`, case-insensitive: `\b(authorization:\s*)(?:(?:bearer|basic|token)\s+)?[^\s"']+` replaced by
   `\1[token]`. Covers Bearer, Basic, `token <x>` and no scheme. The value stops at whitespace or a quote so a JSON
   string stays valid. Order in `mask()`: before `BEARER_RE` is fine either way (BEARER_RE then re-matches nothing
   because the value is `[token]`, fewer than 16 chars).
3. New `CURL_USER_RE`: `(?<!\S)(-u|--user)(\s+|=)(?:"[^"]*:[^"]*"|'[^']*:[^']*'|[^\s:"']+:\S+)` replaced by
   `\1\2[token]`. Requires a colon in the value, so `sudo -u bob` and `git push -u origin` are unchanged (ordinary
   text stays intact, AC3). Note `\S+` on a user:pass inside a JSON string could swallow a closing quote: the
   unquoted branch must exclude `"` (use `[^\s"']+`) so the JSON line survives; `mask_data` masks per string anyway.
4. `mask()` calls the two new substitutions beside the existing token rules. Marker: `[token]`, consistent with the
   file.

Failure modes: no match leaves text unchanged (heuristic, documented in the docstring; update the docstring to list
headers and curl credentials). A `-u` with a quoted password containing a space is handled by the quoted branch; an
unterminated quote masks nothing extra beyond the match (it must not run past the end of the string). Regex cost is
linear; no nested quantifiers.

## Acceptance criteria

1. A test that fails on current `main` and passes after: `T.mask` fully hides each of `ghp_`, `gho_`, `ghu_`, `ghs_`,
   `ghr_` + 30 alphanumerics (fake values built at runtime, like `FAKE_TOKEN`), `Authorization: Bearer <fake>`,
   `Authorization: Basic <fake>`, `Authorization: token <fake>`, and `curl -u alice:<fake> https://x`; the fake
   value is absent from the output.
2. The same forms are masked in the Markdown digest (`T.mask(TR.render(d))` and `trace.py` CLI stdout) and in the
   JSON digest (`trace.py --json` stdout parses with `json.loads` and holds no fake value).
3. Plain text without secrets is unchanged by `mask()`: e.g. `sudo -u bob ls`, `git push -u origin main`,
   `Authorization is required`, `ghx_abc`, and a `gh` word in prose.
4. Boundary table (parametrized, each with a reason in the id/comment): token shorter than 20 chars after the prefix
   stays; `--user=alice:pw` (equals form); quoted `-u "alice:pa ss"` (space in password); lowercase `authorization:`
   (case); `Authorization:` with no scheme; header inside a JSON string keeps the JSON parseable via `mask_data`;
   a `ghs_` token embedded in a URL (`https://x:ghs_...@github.com`); Windows-style value in a PowerShell
   `-H "Authorization: Bearer ..."` command line.
5. Drift test: loads `plugins/brain-hud/skills/mistake-brain/scripts/host_layout.py` by path, and for every probe
   in the shared list asserts both `T.mask` and `redact_secrets` remove the secret.
6. `python -m pytest plugins/retro/tests -q` passes (existing tests included), and the new tests run in the
   `inspector.yml` job (they live under `plugins/retro/tests`, already run on Linux and Windows).
7. The PR shows the new test failing on the pre-fix code (command and output) per repo CLAUDE.md, and the premerge
   check row is added to `plugins/inspector/evals/premerge/README.md`. No session link in commits or PR.

## Open questions

- Reuse of `_SECRETS` at run time was rejected for the install-independence reason above; if the owner wants a hard
  import, that is a separate design (shared package). Assumed: own patterns plus drift test.

## Code map

- `plugins/retro/skills/distill/scripts/transcript.py:453-465` regexes (EMAIL_RE, GUID_RE, TOKEN_RE 455-456,
  BEARER_RE 457, SESSION_URL_RE, PRIVATE_KEY_RE 463, ADO_PAT_RE 464, HOME_RE). CHANGE: TOKEN_RE widened, two regexes
  added; the one place the shapes live.
- `.../transcript.py:468-477` `mask_data(obj)` masks every string in decoded JSON (JSON digest path). Depends, no edit.
- `.../transcript.py:480-491` `mask(text: str) -> str`: ordered sub chain. CHANGE: call new rules, update docstring.
- `plugins/retro/skills/distill/scripts/trace.py:48,102,136-167` `digest`, `render`, `main`; `--json` uses
  `T.mask_data(d)`, Markdown uses `T.mask(render(d))`, `--no-mask` bypasses. Depends, no edit.
- `plugins/retro/skills/agent-audit/scripts/agents.py:539` calls `T.mask(text)`. Depends, gets the fix for free.
- `plugins/retro/skills/distill/scripts/lint_skill.py:31` lists `T.TOKEN_RE`, `T.BEARER_RE` as lint checks. Gets
  widened TOKEN_RE automatically; adding the new regexes to its list is optional and out of scope.
- `plugins/brain-hud/skills/mistake-brain/scripts/host_layout.py:71-107` `_SECRETS`, `redact_secrets(text)->str`.
  Reference copy of the shapes (gh[pousr]_ line 84, Authorization line 79, curl -u line 82). OUT of scope, read only
  (loaded by path in the drift test).
- `plugins/retro/tests/test_retro.py:21` `FAKE_TOKEN`, `:238-243` `test_mask_hides_...`, `:246-250`
  `test_trace_cli_masks_by_default` (subprocess pattern to copy). Sys.path setup lines 11-19 (`T`, `TR`).
- `plugins/retro/tests/test_review_fixes.py:197-202` private-key mask test; model for new test style. New tests go
  in one of these files (builder's choice, prefer `test_review_fixes.py` or a new `test_mask_secrets.py` in the same
  dir; it is collected by the same pytest command). CHANGE/CREATE: tests are required by the repo rules.
- `plugins/inspector/evals/premerge/README.md`: add the premerge row (repo CLAUDE.md). CHANGE.
- `.github/workflows/inspector.yml:20-21,39-40` runs `plugins/retro/tests` on Linux and Windows. No edit.

Copies of the masking logic: (1) retro `transcript.py` TOKEN_RE/mask: IN scope. (2) brain-hud `host_layout.py`
`_SECRETS`/`redact_secrets`: OUT (already correct; only read by the drift test). (3) `lint_skill.py` reuses
`T.TOKEN_RE`: no copy, inherits. No bundled or generated copies found (grep of TOKEN_RE/BEARER_RE across the repo).

Commands:
- `python -m pytest plugins/retro/tests -q`
- `python -m pytest plugins/retro/tests -q -k mask` (new tests)
- Failing-first evidence: run the new test before editing `transcript.py`.

SIZE: small
