# Stabilizing the factory: tests, then decisions, then a transition table

The factory's hooks module, `plugins/factory/hooks/register.tsx`, is 2,425 lines and 107 functions: a run's
phases, the issue queue, the intake, reviewer routing, resume after a restart, the base check, the sync with the
latest base, autoMerge, the band and the pane. The worst bugs of #174's review were where two features met:
- a resumed build skipped the post-build checks (F5);
- the sync with the latest base didn't know about a check that already failed on the base (F6);
- `run.json` wasn't written at the first step, so resume found nothing (F7).

Each was in the path between two functions, not inside one. The goal is clear ownership: each decision in one
place, with tests of its own, and the paths between features under test. A smaller file follows from that, but
size is not the target.

**Scope of the freeze.** No new factory features while steps A to C are open. Fixes to bugs found on the way go
in as their own PRs, each with its test, as `CLAUDE.md` asks. Other plugins aren't frozen.

## The hooks compiler: what is known

`register.tsx` says some CLI releases' hooks compiler follows `$` (the engine) only into functions declared in
the same file. A module that breaks the rule doesn't load at all. The evidence:
- **Where it was seen:** commit `28b60c5` (2026-11-08) saw it on CLI 2.1.286, inlined one helper
  (`goalRunThere`), and checked the module loads on 2.1.286 and 2.1.312.
- **Where it doesn't hold:** CI pins 2.1.312, which allows `$` across files. This session ran 2.1.329.
- **What other mods already do:** brain-hud, followups and goal-run pass `$` into `hasCommand` and `projectOf`
  imported from `./runtime`. They pass CI. On 2.1.286 they would fail to load just as the factory did.

So the rule is a constraint only if 2.1.286 is still supported, and nothing else in the repository supports it.
Step B doesn't depend on it: it moves pure logic, which needs no `$`. Before any step moves a function that
takes `$`, that PR shows the module loading and its tests passing on the CLI version CI pins. It either records
2.1.286 as unsupported, or keeps such functions in `register.tsx`.

## Steps

Each step is one PR, reviewed by running before the next starts (`CLAUDE.md`, Pull requests).

### A. Characterization and interaction tests (no code change)

Pin today's behaviour before anything moves.

1. **Characterization.** For each phase, a test of what the run does on entering it and on each event it waits
   for: an agent's answer, a check's result, the person's command, a restart. Many exist; this fills the gaps
   and names them by phase.
2. **Interactions.** One table-driven file walks the paths where features meet, from the engine fake:
   - **restart** in each phase,
   - **×** a check that fails on the base or only on the branch,
   - **×** a base that moved or didn't,
   - **×** autoMerge on or off.

   Each row writes down the expected end:
   - the phase the run ends in;
   - whether the builder was sent;
   - whether the PR prompt asks to merge.

   Rows are chosen for the pairs the bugs came from and their neighbours, each with a reason. The table doesn't
   claim every combination.
3. **Regressions F5–F7.** Each is a row that fails on the code before its fix. The check: run the row against
   that commit in a scratch worktree, and record the command and its output in the PR.

Done when the suite is green on today's code, and F5, F6 and F7 each fail on their pre-fix commit.

### B. Decisions out of `register.tsx` (no behaviour change)

Move pure decisions into modules named for what they decide, keeping their tests:

| Module | What moves there |
|---|---|
| `resume.ts` | `resumeState` and matching an earlier run |
| `basecheck.ts` | the failure shape; "fails the same on the base" |
| `prompts.ts` | the prompt builders now in `flow.ts` |
| `ledger.ts` | findings, outcomes, NOT CHECKED |

`register.tsx` keeps reading state, calling a decision, and applying its result.

Done when step A's tests pass unchanged (no assertion edited), and each moved decision has a test that calls
it directly. Line counts are reported, not targeted.

### C. A transition table (a behaviour change, said as one)

`phases.ts` gets one table of the moves a run may make, `Record<Phase, Phase[]>`, each edge with its reason.
`patch` checks every phase change against it.

1. **First release: record only.** A move the table doesn't list is applied as today, and written to the run's
   record as `unlisted move <from> -> <to>`, so a gap in the table can't stop a real run.
2. **Then enforce.** Once runs have gone by with no unlisted move recorded, an unlisted move is refused: the run
   stops for the person, with the move named. This flip is its own PR, in the CHANGELOG as a behaviour change.

Tests:
- **valid:** every edge in the table is taken by some test;
- **invalid:** a move off the table is recorded (then refused);
- **resume:** `run.json` files as 0.28.0 writes them, for each phase, saved as fixtures, resume to a state the
  table allows;
- **reach:** every phase reachable from `intake` can reach `done` or `stopped`.

## Not in this work

- **No change to the agents' prompts or the commands.** Prompts move to `prompts.ts` word for word.
- **No paid reviewer experiments.** The reviewers' scratch repository (`docs/open-items.md`, item 1) waits until
  C is done.
