# Code review: claudemod (2026-11-02, at `ba94169`)

A review of the whole repository and of each mod on its own. Each item says where the problem is, why it
matters, and a suggested fix. Items are ordered by priority inside each section: **P1** fix first,
**P2** worth fixing, **P3** minor or polish.

## What was run

| Suite | Result |
|---|---|
| `claude plugin test plugins/<mod>` for all 7 mods | all pass except one factory test (below) |
| `python -m pytest plugins/brain-hud/tests/skill` | 238 passed |
| `node tools/sync-texts.mjs --check` | clean |

The factory test **"a run that seems stuck says where it is > a check that runs out of time stops the run
for the person"** fails here every time (3 of 3 on `main`, and on every commit since it was added in
`06b925f`). It passes on GitHub CI, so it depends on the machine, but it is not a one-off. At `06b925f` its
hang also broke 50 other tests in the same file. See factory F2.

Not verified: the engine's type definitions (`claude-code` d.ts) are not in the repo (they are generated
into the gitignored `.claude-plugin/types/`), so assumptions about the engine API (for example which
surfaces can draw `Svg`) were not checked against it. factory and goal-run were read in their risky parts,
not line by line.

---

## Repository-wide

### R1 (P2) CI installs whatever CLI version is newest
`.github/workflows/mods.yml:16` runs `npm i -g @anthropic-ai/claude-code` with no version. A new CLI release
can turn CI red with no change in this repo, or hide a regression. **Fix:** pin a version (`@x.y.z`) and
bump it on purpose. Optionally pin the actions (`actions/checkout`, `setup-node`, `setup-python`) to a SHA.

### R2 (P2) No typecheck in CI
Every mod's `tsconfig.json` extends `./.claude-plugin/types/tsconfig.json`, which is gitignored and
generated. Nothing runs `tsc --noEmit`, so a type error shows up only if a test happens to run that code.
**Fix:** add a CI step that generates the types (whatever `claude plugin test` uses) and runs
`tsc --noEmit -p plugins/<mod>` in the matrix.

### R3 (P2) Duplicated logic across mods
These are near copies in followups and goal-run:
- `projectOf` (`followups/hooks/register.tsx:240`, `goal-run/hooks/register.tsx:228`)
- `checkFactory` (`followups/hooks/register.tsx:381`, `goal-run/hooks/register.tsx:332`)
- the cross-session save/sync/merge pattern (`base`/`seen` atoms, `mergeLists` at followups:264,
  `mergeGoal` at goal-run:245)

**Fix:** the `shared/` and `tools/sync-texts.mjs` mechanism already copies shared code into each mod.
Extend it (or add `shared/project.ts`) for these helpers.

### R4 (P3) Two mods both block the same Stop
followups (`register.tsx:585`) and goal-run (`register.tsx:870`) both return `block` from `classic.Stop`.
Each one passes when `r.block` is already set, which is correct. But after followups blocks, the next Stop
has `stop_hook_active` set, so goal-run's "go on to the next task" nudge never fires in that turn.
**Fix:** decide which one should win, or have goal-run nudge on the next Stop even when
`stop_hook_active` is set, if the earlier block was not its own. Add a cross-mod test.

### R5 (P3) Surface checks are inconsistent between mods
clawd-hud draws SVG only on `desktop`/`vscode` (`clawd-hud/hooks/register.tsx:310`). task-hud draws SVG on
every surface except `terminal` (`task-hud/hooks/register.tsx:295`, `:337`). On any other surface (mobile,
web) task-hud would resolve an `Svg` that may not exist. **Fix:** one shared `canSvg(surface)` helper,
checked against the engine's actual surface list.

---

## factory

### F1 (P1) The agents' command guard is easy to get around
`hooks/route.ts` `forbiddenCommand` matches the start of each shell segment. Tested: all of these are
**allowed**:

```
git -c foo=bar push        git --no-pager push        /usr/bin/git push
env git push               bash -c "git push"         sh -c 'git push'
eval git push              (git push)                 $(git push)
`git push`                 xargs git push             time git push
nohup git push             npx vercel deploy
```

Also:
- Only the `Bash` tool is checked. `PowerShell` is not.
- MCP tools are not checked at all. In a session with the GitHub MCP server, a run agent can call
  `mcp__github__push_files`, `mcp__github__create_or_update_file` or `mcp__github__create_pull_request`
  directly.
- The hook at `hooks/register.tsx:1108` ends in `.catch(($, e, next) => next(e))`, so if it throws, the
  call goes through.

**Fix:**
1. Deny by tool name for the run's agents: `mcp__github__*` write tools (push_files, create_or_update_file,
   delete_file, create_pull_request, merge_pull_request, create_branch, ...) and `PowerShell` with the same
   patterns.
2. Before matching, normalize each segment: strip `(`, `$(`, backticks, and the wrappers
   `env|time|nohup|xargs|eval|bash -c|sh -c` (re-parse the `-c` argument), take the basename of
   `/usr/bin/git`, and skip git's global options (`-c k=v`, `--no-pager`, `--git-dir=...`, `-C dir`)
   before the subcommand.
3. Match `npx|pnpm dlx|bunx <deploy-cli>` too.
4. Document in the README that this is a best-effort guard against mistakes, not a security boundary.
5. Add the cases above to `tests/factory.test.tsx`.

### F2 (P1) One stuck job freezes the whole run (and the flaky test)
`function serial` (`hooks/register.tsx:111`) chains every transition on one module-level `queue`. If a job
never settles (a `$.process.run` or `$.ui.ask` that never returns), every later transition waits on it, and
the run is frozen until the module reloads. `skipRunning` (`:591`) is module-level too.

This is also what the failing test shows: `clock.advance(600_000)` with `FRAME_MS = 700` (`:84`) fires
about 850 frame ticks, each patching state. On a slower machine that passes the test's 5-second limit, the
job never finishes, and at `06b925f` the stuck `queue` broke 50 later tests.

**Fix:**
- Wrap each `serial` job in a time limit; on timeout, record it and `block()` the run for a Retry.
- Reset `queue` and `skipRunning` in `session.start`.
- Stop the frame ticker while a check is running (the band's seconds come from `now`), or make the tick
  cheaper.
- In the test, raise its timeout or advance the clock in fewer, larger steps.

### F3 (P1) pytest is detected in any repository with a `tests/` folder
`hooks/checks.ts:350` sets `pyTests` true when the root has a `tests` directory, and `pythonChecks`
(`:77`) then adds `python -m pytest -q`. In a Node (or any non-Python) project with a root `tests/`:
- pytest installed: exit code 5 ("no tests collected"), counted as a failure.
- pytest not installed: `python` starts and exits 1 with "No module named pytest", also counted as a
  failure, not as "not installed".

Either way the builder is sent back to fix a check that has nothing to do with its change.

**Fix:**
- Count `tests/` only if it holds `test_*.py` / `*_test.py` (one more list of that directory).
- In `runChecks`, treat pytest exit 5 as "no tests" (skip, noted), and "No module named pytest" as
  `isMissing`.
- Add tests for both.

### F4 (P2) `pyproject.toml` that wasn't read counts as pytest
`checks.ts:78`: `d.texts[f] == null` (file not read because `MAX_READS` was hit, or unreadable) makes
`configured` true. **Fix:** only count a file that was read and mentions pytest; an unread one is a
warning.

### F5 (P3) The "Run them" approval covers less than it seems
`approveAuto` asks again only when a file in `CHECK_CONFIGS` changes. Between rounds the builder can rewrite
any test file and it runs without asking. The question text already says this, so it is disclosed. **Fix
(optional):** say it again in the README's factory section, so nobody reads "asks again when config
changes" as a sandbox.

### F6 (P3) Already tracked
Two tests fail on Windows (`docs/OPEN_ISSUES.md`), likely path separators.

---

## brain-hud

### B1 (P1) Text from workers goes into the next session's context
`handoffEntry` (`hooks/journal.ts:133`) writes workers' open questions and report text into MISTAKES.md as
plain markdown. `brief_on_session_start.py` reads MISTAKES.md into the next session's context. A worker's
report can quote a web page or a file it read, so instruction-like text there carries into later sessions.
followups already guards against this for CLAUDE.md (`quoted()`, `followups/hooks/register.tsx:402`).

**Fix:** quote each piece of worker text as an inline code span (backticks replaced, one line), as
followups does, and add a note line that the entries are quoted notes, not instructions. Same for
`contextLine` (`journal.ts`) when it puts `last.text` beside the prompt.

### B2 (P2) The handoff changes a tracked file by default
`handOff` (`hooks/register.tsx:225`) runs on `session.end` with `handoffDraft` on by default and writes
MISTAKES.md, which is in git. Every session that ends with something open leaves the working tree dirty.
**Fix:** make the default `off`, or write the draft under `.claude/brain/` (already git-excluded) and have
`route` pick it up from there.

### B3 (P2) The Python hooks can exit non-zero
The `draft_mistake_on_revert.py` docstring says the hook always exits 0, but `read_text`/`write_text`
(`:154`, `:175`) are not in a `try`; the same holds in `revert_stop_hook.py:155/172` and
`auto_pipeline_on_mistakes_edit.py:84`. A decode or permission error prints a traceback and exits 1.
**Fix:** wrap `main()` in `try/except Exception: return 0` in each hook (or once in `run.sh` with
`|| exit 0`), and add a test that feeds an unreadable MISTAKES.md.

### B4 (P3) The same marker is defined twice
`MARKER` is in `hooks/journal.ts` and in `skills/mistake-brain/scripts/host_layout.py`. **Fix:** a test
that asserts the two strings are equal (if none exists).

### B5 (P3) Polling every 4 seconds
The 4-second poll (`POLL_MS`) stats MISTAKES.md and the memory paths and lists every PARA folder. Fine for
a small memory. **Fix (optional):** use a file watcher if the engine offers one, or poll more slowly while
nothing changes.

---

## followups

### FU1 (P2) The Docs and README exports aren't quoted
`section()` (`hooks/register.tsx:404`, `asCode = target === 'memory'` at `:406`) quotes items only for
CLAUDE.md. `docs/FOLLOW-UPS.md` and `README.md` get the titles as prose, and titles can come from the
haiku sweep or a sub-agent's report. Claude reads these files later too. **Fix:** quote everywhere, or at
least the `detail` and items from the sweep or a report.

### FU2 (P2) `done` doesn't check the item was started
The `done` tool (`:545`) marks any open item done, and also matches by title, not only by id. The rule
"only for items started that way" is in the prompt alone. **Fix:** accept only items that are
`in_progress` (or in `startedHere`), match by id only, and deny otherwise with a clear message.

### FU3 (P2) A bad saved entry breaks session start
`migrate()` (`:72`) destructures each saved entry; a `null` or non-object entry in the store throws, and
`session.start` fails. **Fix:** filter out entries that aren't objects with a string `id` and `title`.

### FU4 (P2) The stop phrase `'פער'` is too common
`STOP_PHRASES` (`:40`) includes `'פער'` (gap), a common Hebrew word. Expect false stops, each costing a
turn. The comment already left out `'בהמשך'` for this reason. **Fix:** remove it, or use a narrower phrase
(`'פער ידוע'`, `'פער פתוח'`).

### FU5 (P3) A sub-agent's open questions turn off the end-of-turn check
`if (await offerOpenItems(...)) isFlagged = true` (`:566`): once any of them are offered, the Stop check
is skipped for the whole turn, even for other loose ends the main reply leaves open. **Fix:** keep a
separate flag, or compare the reply's phrases with what was offered.

### FU6 (P3) Two sessions saving at once can lose a change
`save()` reads, merges and writes the store with no lock, so two sessions saving at the same moment can
lose one change. Rare; document it, or retry once if the store changed between the read and the write.

---

## goal-run

### G1 (P2) A missing usage field gives NaN
`stepTokens` (`hooks/register.tsx:122`) adds usage fields with no `?? 0`, so a missing cache field makes
the count NaN, and it is saved. **Fix:** `(u.x ?? 0)` for each field. task-hud has the same problem (T1).

### G2 (P3) Tokens of unrelated sub-agents count against the active task
Every sub-agent's tokens go to the task in progress, even if the agent has nothing to do with it. Probably
intended; say so in the README.

### G3 (P3) Duplicated helpers
See R3.

---

## task-hud

### T1 (P2) A missing usage field gives NaN
`turn.step` (`hooks/register.tsx:266`) adds four usage fields with no `?? 0`, so a missing field shows as
"NaN tokens". **Fix:** `?? 0` for each field.

### T2 (P2) SVG on every surface but the terminal
Every surface except `terminal` gets an SVG (`:295`, `:337`). See R5.

### T3 (P3) A long command marks its agent as failed
`STALE_MS` is 10 minutes (`:28`). A single Bash command that runs longer (for example a factory check at its
10-minute limit) marks the agent as Stopped until its next call. **Fix:** a longer limit, or reset
`updatedAt` on `turn.step` too (it already revives).

### T4 (P3) `isPersons` can be stale
`let isPersons` (`:162`) is a closure variable set in `prompt.submit`. A turn that starts without one keeps
the previous value. Minor.

---

## clawd-hud

### C1 (P3) The context label can show "NaNk"
`tok(c.window)` (`hooks/register.tsx:374`) shows "NaNk" if `tokens` is set but `window` is missing.
**Fix:** show the window only when it's a finite number.

### C2 (P3) A bad reset time shows "resets in –"
`resetAt` (`:64`) with an invalid `resetsAt` returns NaN, and the band shows "resets in –". **Fix:** check
`Number.isFinite` and fall back to "no reading yet".

### C3 (P3) Compaction restarts the cache timer
Any context change restarts the cache timer (`:242`), compaction included. Small inaccuracy; document it,
or skip it when the change is a compaction, if the event says so.

### C4 (P3) The frame timer runs while idle
The 125 ms frame timer runs even while idle; it returns early, so it's cheap. **Optional:** stretch the
interval while idle or resting.

---

## rtl-toggle

### RT1 (P3) Streaming fills the cache with partial texts
`toRtl` calls `remember()` (`hooks/rtl.ts:230`) for every streamed chunk, so partial texts fill the LRU and
push out finished messages. `memo.size` (`:194`) counts only the key's length, not the result's. **Fix:**
don't cache a text that the stream memo will keep extending (or only cache when it's not a prefix
extension), and count `text.length + result.length`.

### RT2 (P3) `toggle` isn't in the hint
`/rtl toggle` is accepted but not listed in `argumentHint`.

---

## Suggested order

1. factory F1 (guard: MCP tools and normalization), F3 (pytest detection), F2 (`serial` time limit and the
   test).
2. brain-hud B1 (quote worker text), B2 (handoff default), B3 (hooks always exit 0).
3. R1 (pin the CLI in CI) and R2 (typecheck in CI).
4. followups FU1 to FU4, plus G1 and T1 (NaN tokens).
5. The rest (P3).

After each fix: run `claude plugin test plugins/<mod>`, and for brain-hud also
`python -m pytest plugins/brain-hud/tests/skill`. Bump the mod's version in its
`.claude-plugin/plugin.json`, and run `node tools/sync-texts.mjs` if `shared/texts.ts` changed.
