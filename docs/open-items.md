# Open items

What is known to be open after factory 0.28.0, inspector 0.9.0 and retro 0.3.0 (2026-11-20). Every finding of
the reviews of #174–#177, including two outside reviews, is fixed and has a test, and so is the one bug
`/inspector:inspect` found after the release (the `-diff`/`binary` attribute miss, fixed in the PR that removed
it from this list). What follows is work that was planned but not built, things nobody has been able to check, and decisions
waiting on the owner.

Each item says where it would go (as `/retro:distill` routes a lesson): **check**, **test**, **access**,
**guidance**, **skill**, **model** or **no-change**. Close an item by deleting its row in the PR that closes it.

## Planned, not built

| # | Item | Where | Why it matters | Next step |
|---|---|---|---|---|
| 1 | Let the factory's reviewers build a scratch repository and run the PR's code on hard inputs | access (factory guard) | The outside reviews of #174 and #176 found six bugs by running experiments; the factory's reviewers only read the diff, and their guard allows only the configured checks. The code reviewer wrote under NOT CHECKED that it couldn't trace the remerge fallback, next to where the octopus bug was. | Allow writes and git commands under the session's scratch for review agents, read-only everywhere else; verify by re-running a review of #174 before its fixes and seeing whether it finds N2. |
| 2 | A fresh start for an issue whose earlier branch is still there | guidance → code (factory) | `/factory run <n>` on such an issue offers `/factory resume`; `/factory new: <feature>` starts over but without the issue's link (no comment, no `Closes #n`). The way out today is removing the old worktree by hand. | Add `/factory run <n> new` (or `fresh`), with a test beside the start-offer test. |

## Not checked: needs a machine or a setup this environment doesn't have

| # | Item | Where | What is unknown | How to check |
|---|---|---|---|---|
| 3 | Cursor's project-folder names | test (retro) | `transcript.py candidates()` matches `~/.cursor/projects/<name>` against the project's path, normalized. Two projects whose paths differ only in case or punctuation could be read as one, so distill would list the other's transcripts. Never seen against a real Cursor install. | On a machine with Cursor: list `~/.cursor/projects`, compare with `project_slug(cwd)`, and turn what you see into a fixture test. |
| 4 | The secret scan on git older than 2.36 | check (CI) | Without `--diff-merges=remerge` the scan falls back to the first-parent diff. The matrix (`plugins/inspector/tests/test_scan_matrix.py`) runs only on the git CI has. | A CI job that runs the matrix with an older git (a container image with git 2.30 or 2.34). |
| 5 | Windows | test (retro, inspector) | Windows paths are covered by unit tests with synthetic strings; nothing has run on Windows. | Run both test suites on a Windows runner. |
| 6 | `git filter-branch` in a linked worktree with untracked files the setup made | test (factory) | Checked by hand in a plain worktree only. A miss fails closed: the branch is re-read and the run stops if a session link remains. | An integration test on a real repository with a linked worktree and a `node_modules`. |

## Measured on too few runs

| # | Item | Where | What the numbers rest on | Next step |
|---|---|---|---|---|
| 7 | Whether sonnet is enough for the factory's intake and approver | model | Every run in `plugins/factory/docs/bench/2026-11-19-budgets.md` used opus for both. | Runs on both models, then `/retro:agent-audit --all` and its "By model" table. |
| 8 | Budgets for a large feature's builder, and for the skeptic | model / no-change | The builder's budget comes from medium features; the skeptic's from one run. | Re-measure after a few large runs (same command). |

## Limits by design (no change planned)

| # | Item | Why it stays |
|---|---|---|
| 9 | Secret detection finds known shapes only | A token in no known shape isn't caught. Masking and the scan say so; widening it trades for false positives. |
| 10 | agent-audit judges a past write by today's paths | A path's meaning at the time of the run (a symlink, a moved folder) isn't recorded in the transcript. Relative paths are resolved against the folder given now (`--cwd`), not the run's, and the audit doesn't report "unknown" when the two may differ. |
| 11 | The pre-merge check is a triage, not a review | Its four questions don't cover logic; its "none" isn't assurance. The evals table (`plugins/inspector/evals/premerge/README.md`) records what it missed and the one flag that led to a fix. |

## Decisions for the owner

| # | Item | Options |
|---|---|---|
| 12 | Three commits on `main` carry a `Claude-Session:` line (`3a65d1c`, `c290bc2`, `75ed65d`), from before the factory took them out | Leave them (the link opens only for the account that owns the session), or rewrite `main`'s history and force-push, which breaks every existing clone and fork. |

## Housekeeping in the session that did this work

- The factory's fixes load in a new session only; until then the session runs 0.27.0.
- A temporary `gh` wrapper was installed in that cloud session (`/root/.local/bin/gh`) while GitHub's GraphQL API was refused there. It lives only in that container, and isn't needed once factory 0.28.0 is loaded.
