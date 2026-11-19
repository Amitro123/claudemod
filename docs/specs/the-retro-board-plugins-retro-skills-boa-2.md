# Retro board: confirmations and `get --max-age`

## Problem

On the retro board (`board.py`), an `add` with the value a key already has returns `exists` and writes
nothing, so a fact keeps the timestamp of its first write. An agent reading the board can't tell "the branch
is not on the remote", checked a minute ago, from the same line written an hour ago and never checked
again. That matters for volatile facts (branch state, sign-in state, remote heads). The people affected are
the main agents and sub-agents that share a board, and the auditor that reads `show`.

## Scope

In:
- An `add` with the key's current value appends a `confirm` record (by, evidence, level, ts). It goes
  through the same validation, secret refusals and lock as any other `add`.
- `get` (text and `--json`) and `show` report each fact's last-confirmed time.
- `get --max-age <minutes>` returns only facts written or confirmed in the last `<minutes>` minutes.
- Both `board.py` copies stay byte-identical. Also in: the module docstring, the board `SKILL.md`, the retro
  `CHANGELOG.md`, and tests in `plugins/retro/tests/test_board.py`.

Out of scope:
- `/retro:agent-audit` (`agents.py`) counting or using confirms. `load_board` already keeps only
  `type == "fact"`, so confirm records are ignored there, and that stays as it is.
- Expiry or deletion of facts. `--max-age` filters what one read returns and changes nothing on disk.
- Any change to the lock (`Locked`), `SECRET_RE`, `KEY_RE`, `check()` limits, the twin refusal or `--new-key`.
- Changing a fact's level through a confirm. A higher-level confirm does not promote the fact.
- `keys` output, `seed`'s set of facts, the inspector plugin's `SKILL.md`/`CHANGELOG.md`, and plugin version bumps.

## Design

### Data: the confirm record

It is appended to the same JSONL file, one locked append:

```json
{"type": "confirm", "id": <len(recs)+1>, "key": "<key>", "value": "<value>", "fact": <id of the current fact>,
 "by": "<by>", "evidence": "<evidence>", "level": "<level>", "ts": "<now()>"}
```

- `id` uses the same counter as facts (`len(recs) + 1` under the lock), so record ids stay unique and
  consecutive across all record types. The parallel-writers test depends on this.
- `fact` ties the confirm to one fact record. When a later `add` supersedes the fact, the confirms of the
  old fact do not carry over to the new one.
- `value` is redundant but lets an audit read the confirm alone. It has already passed `check()`.
- No other field changes on the fact record. Records are append-only and nothing is rewritten.

### `add()` (board.py:160-187)

All checks before the lock stay where they are and run for a confirm too: `check()`, empty evidence, secret
in evidence, secret in key or `--by`, and `--by` shape. Under the lock, the branch `old and old["value"] ==
value` (line 174) now appends the confirm record and returns `("confirmed", confirm_rec)` instead of
`("exists", old)`. The twin check (line 176) still runs only when there is no `old`, so nothing changes there.
The return set becomes `added | superseded | confirmed`; `exists` is no longer returned.

### Last-confirmed time

Add a helper `last_confirmed(recs) -> dict[int, str]` that maps a fact id to the latest `ts` among that
fact's own `ts` and the `ts` of every `confirm` whose `fact` equals that id. It also returns a count of
confirms per fact (in the same helper, or a second one).

Compare timestamps after parsing with `datetime.fromisoformat`. If a `ts` won't parse (a hand-edited
file), skip that confirm. If the fact's own `ts` won't parse, use the raw string.

- `get()` (board.py:190-200) adds two fields to each returned dict: `last_confirmed` (ISO string, always
  present, equal to `ts` when the fact was never confirmed) and `confirms` (int, 0 when never confirmed).
  `--json` prints them as part of each fact. With `--history`, superseded facts get their own values.
- `get` text output (board.py:305-307): after the evidence, inside the bracket, print `, written <ts>`, plus
  `, last confirmed <last_confirmed>` when `confirms > 0`. The line still starts `<key> = <value>    [`.
- `show` (board.py:336-337): each fact line becomes `[<level>, by <by>, <ts>]`, or
  `[<level>, by <by>, <ts>, last confirmed <last_confirmed> (<n>x)]` when confirmed. The header (line 333)
  adds `, <C> confirms` inside its parentheses, after the record count. The writers/readers counts and the
  twin lines are unchanged. Confirm records are not counted as facts or writers.
- The CLI `add` print (line 296) for `confirmed` is `confirmed: <key> = <value> (fact #<fact>)`.
- `seed` (board.py:308-317): the counter's key `exists` becomes `confirmed`. Seeding twice now appends
  confirm records (the context re-confirms what it knew) and adds no fact records.

### `get --max-age <minutes>`

- New CLI option on `get`: `--max-age`, `type=float`, with a help text. New parameter on `get()`:
  `max_age: float | None = None`.
- Validation in `get()`, before the lock: `max_age` must be finite and `> 0`, or `ValueError("--max-age:
  minutes, a number above 0")`. The CLI `get` branch now catches `ValueError` the way `add` does:
  `refused: <msg>` on stderr, exit 2. This also covers the existing secret-in-`--by` refusal, which today
  shows a traceback. argparse rejects a non-number with exit 2 as usual.
- Filter: keep a fact when `parse(last_confirmed) >= now_utc - max_age minutes`. The bound is inclusive.
  Apply it after the pattern and `--min-level` filters. A fact whose timestamps can't be parsed is
  excluded. With `--history`, each record is filtered on its own `last_confirmed`.
- Read log: the `read` record keeps its shape (`by`, `pattern`, `keys` = the keys returned after all
  filters, `ts`) and adds `"max_age": <minutes>` only when the option was given. The read is still
  logged when the filter leaves nothing.
- Text output with nothing left is `(no facts)`, as today.
- The current time comes from one place (`now()`, or a small `_utcnow()` that `now()` uses) so tests can
  monkeypatch it. Tests may also write records with crafted `ts`, the way `board_session` does
  (test_board.py:221-226).

### Failure modes

| Case | Result |
|---|---|
| Same-value add whose evidence or `--by` holds a secret | Refused (ValueError, exit 2) before the lock; no confirm written |
| Same-value add with empty evidence, bad level or bad key | Refused, same as today |
| Same-value add while another writer holds the lock | Waits (POSIX); Windows raises TimeoutError after `LOCK_WAIT_S` and writes nothing |
| Confirm, then supersede | The new fact's `last_confirmed` is its own `ts`; the old fact keeps its confirms in `--history` |
| `--max-age 0`, negative, `nan`, `inf` | `refused: --max-age ...`, exit 2, nothing logged |
| `--max-age abc` | argparse error, exit 2 |
| Board file missing on `get --max-age` | Same as `get` today (Locked creates it); `(no facts)` |
| Malformed `ts` on a record | Confirm skipped for last-confirmed; fact excluded by `--max-age` |
| Older board without confirm records | Works unchanged; `confirms` = 0 |

### Docs

- Module docstring (board.py:1-22): add `[--max-age MINUTES]` to the `get` usage line. Replace "Adding the
  value a key already has writes nothing" with a sentence saying it appends a confirm (who, evidence, time),
  and that `get`/`show` give each fact's last-confirmed time and `get --max-age` keeps only recent ones.
- `plugins/retro/skills/board/SKILL.md`: in Procedure step 2 or Gotchas, re-adding a fact you checked again
  confirms it. For a volatile fact (branch on remote, signed in), read with `get '<prefix>*' --max-age <n>`
  and re-check what it leaves out. Update the "Superseded is not wrong" gotcha to mention last-confirmed.
  The frontmatter description should no longer say only that a new value supersedes. The skill must still
  pass `lint_skill` (test_board.py:293-296).
- `plugins/retro/CHANGELOG.md`: a new `## Unreleased` section at the top, with an `Added:` bullet for
  confirms, last-confirmed in get/show and `get --max-age`, and a `Changed:` bullet saying a same-value
  `add` now returns `confirmed` and appends a record (was `exists`, writes nothing).
- Copy the retro `board.py` byte-for-byte to `plugins/inspector/skills/audit/scripts/board.py`.

## Acceptance criteria

1. `B.add(f, k, v, ...)` and then `B.add(f, k, v, "check-2", "ev2")` returns `("confirmed", rec)`, where
   `rec["type"] == "confirm"`, `rec["fact"] == 1`, `rec["by"] == "check-2"`, `rec["evidence"] == "ev2"`, and
   `rec["id"] == 2`. The file has exactly 2 lines and one `type: fact` record.
2. After a confirm, `B.get(f, k, "t")[0]["last_confirmed"]` equals the confirm's `ts`, and `["confirms"] == 1`.
   For a never-confirmed fact, `last_confirmed == ts` and `confirms == 0`.
3. After add v1, confirm v1, then add v2 (superseded): the current fact has `confirms == 0`. In
   `get(..., history=True)` the v1 record has `confirms == 1`.
4. A same-value `add` whose evidence contains `TOKEN`, or whose `--by` is `TOKEN`, raises `ValueError`. The
   file then holds no `"type": "confirm"` line.
5. Under the Windows lock stand-in (`_AlwaysLocked`, as in test_board.py:152-159), a same-value `add` on a
   board that holds the fact raises `TimeoutError`, and the file is unchanged.
6. `test_parallel_writers_lose_nothing`, extended so each writer also re-adds one of its facts with the same
   value: every record lands, and the ids over all records are exactly `1..N` with no duplicates.
7. `get(f, None, "t", max_age=30)` returns a fact with `ts` 10 minutes old and leaves out one with `ts` 2
   hours old. Once the old fact gets a confirm with a current `ts`, the same call returns it.
8. `get(..., max_age=0)` and `max_age=-5` raise `ValueError` matching `--max-age`. The CLI
   `get --by x --max-age 0` exits 2 with `refused:` on stderr and appends no `read` record.
9. The `read` record of a `get` with `max_age=30` has `"max_age": 30` and `keys` equal to the keys it
   returned. A `get` without it has no `max_age` field.
10. CLI: `add a.b 1` twice prints `confirmed: a.b = 1 (fact #1)` on the second call, with exit 0.
    `get 'a.*' --by y` output contains `a.b = 1` and `last confirmed`. `show` output contains
    `last confirmed` and `1 confirms`.
11. `seed` twice on the same context: the second run prints a count of `confirmed` and no `exists`.
    `get --history` still returns exactly the number of facts.
12. `test_audit_skill_carries_an_identical_copy` passes: the two `board.py` files are byte-identical.
13. `A.load_board` on a board holding confirm records returns only the fact records. The existing agent-audit
    tests in test_board.py pass unchanged.
14. `test_board_skill_passes_the_skill_lint` passes. SKILL.md mentions `--max-age` and confirm. The retro
    CHANGELOG has the Added/Changed entries above.
15. `python3 -m pytest plugins/retro/tests -q` passes. `test_add_exists_supersede_and_history` is updated to
    expect `confirmed` (renamed if needed).

## Open questions

- Whether a confirm at a higher level (a `reproduced` re-check of a `read` fact) should raise the fact's
  level. I assumed not: it is stored on the confirm record only, and promotion is left for later.
- CHANGELOG heading: I assumed `## Unreleased`, since plugin.json is not in scope for a version bump. The
  builder may use `## 0.2.1 (date)` if the repository's release practice requires it.

## Code map

Files this change edits:

- `plugins/retro/skills/board/scripts/board.py`: holds the feature.
  - :1-22: module docstring and usage, to update.
  - :35-43: constants `LEVELS`, `KEY_RE`, `SECRET_RE`, `MAX_VALUE`, `LOCK_WAIT_S` (do not change).
  - :46-47: `now() -> str` (UTC ISO, seconds); give it one patchable clock source.
  - :50-88: `Locked` (fcntl/msvcrt) (do not change).
  - :91-103: `records(f)`, which parses all JSONL dicts. Confirm records arrive here.
  - :113-118: `current(recs)`, the last `type == fact` per key. Leave confirm records out of it.
  - :121-125: `append(f, rec)`.
  - :128-139: `check(key, value, level)`.
  - :160-187: `add(path, key, value, by, evidence, level="read", new_key=False) -> tuple[str, dict]`. Line
    174-175 is the `exists` branch that becomes the confirm.
  - :190-200: `get(path, pattern, by, min_level="claimed", history=False) -> list[dict]`. Add `max_age` and
    the last-confirmed fields; line 199 appends the read log.
  - :263-342: `main()`. 277-282 has the `get` args (add `--max-age`). 290-296 is the add print. 297-307 is
    get output (wrap it in try/except ValueError). 308-317 is the seed counter (`exists` becomes
    `confirmed`). 322-341 is `show`.
- `plugins/inspector/skills/audit/scripts/board.py`: byte-identical copy (346 lines today). It must equal
  the retro file after the change. **In scope.**
- `plugins/retro/tests/test_board.py`: tests for each criterion.
  - :25-32: `test_add_exists_supersede_and_history`, which asserts `exists` (update it).
  - :128-138: secret refusals in key/by; the pattern for AC 4.
  - :141-159: `_AlwaysLocked` stand-in and the Windows lock test (AC 5).
  - :171-184: `_writer` and the parallel test (AC 6).
  - :187-203: seed twice (AC 11).
  - :206-213: CLI via subprocess with `AGENT_BOARD` (AC 8, 10).
  - :216-218: identical-copy test (AC 12).
  - :221-226: `board_session` shows how to write a record with a crafted `ts`.
  - :293-296: skill lint.
  - Constants: `TOKEN = "ghp_" + "Kp"*18` (:22) and `ADO_SHAPE` (:125).
- `plugins/retro/skills/board/SKILL.md`: user-facing procedure. Document confirm and `--max-age`. Rules are
  at :12-23, Procedure :28-46, Gotchas :61-68.
- `plugins/retro/CHANGELOG.md`: record the behaviour change. The top section is `## 0.2.0` at :3. Add
  `## Unreleased` above it.

Files this change depends on but does not edit:

- `plugins/retro/skills/agent-audit/scripts/agents.py:62-73`: `load_board` keeps only `type == "fact"`, so
  confirm records are ignored. Out of scope; must keep working (AC 13).
- `plugins/retro/tests/test_retro.py`: provides `Writer`, which test_board imports. No board logic.
- `plugins/inspector/skills/audit/SKILL.md:38-71`: tells auditors to use `board.py seed/get/add/keys/show`.
  No change needed; the CLI stays compatible. Out of scope.
- `plugins/retro/skills/agent-audit/references/brief-contract.md`, `plugins/inspector/agents/auditor.md`,
  `plugins/inspector/CHANGELOG.md`, `README.md`: mention board.py and need no change. Out of scope.

Copies of the logic:

- `plugins/retro/skills/board/scripts/board.py`: source. In scope.
- `plugins/inspector/skills/audit/scripts/board.py`: byte copy. In scope; overwrite it with the source.
- No other implementation of add/get exists. `agents.py` has its own minimal reader (`load_board`). Out of
  scope, and it is unaffected.

Test commands (from the worktree root):

```
python3 -m pytest plugins/retro/tests/test_board.py -q
python3 -m pytest plugins/retro/tests -q
cmp plugins/retro/skills/board/scripts/board.py plugins/inspector/skills/audit/scripts/board.py
```

Before the PR merges, CLAUDE.md requires running
`python3 plugins/inspector/skills/inspect/scripts/premerge.py --repo . --base origin/main --title "<PR title>"`,
posting its output as a PR comment, and adding a row to `plugins/inspector/evals/premerge/README.md`.
