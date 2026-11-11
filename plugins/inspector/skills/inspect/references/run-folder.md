# Where the run folder lives

The run folder holds everything a run writes and reads: `evidence.json`, `evidence.md`, `cases/`, `plan/`
(the RUN PLAN and every agent's prompt), and what the agents write (`brief.md`, `cards/`, `sweep-<k>.json`,
`verdicts-<k>.json`). The agents write their own files, so the folder has to be somewhere their Write tool
is allowed without asking.

**Default: `<working tree>/.inspector-run/<time>/`**, with `.inspector-run/.gitignore` holding `*`, so `git status`
stays clean and nothing is committed. `--out <folder>` overrides it.

Why not `.git/inspector/` (the earlier default). Measured (Claude Code 2.1.292, a throwaway repository,
headless, `--permission-mode acceptEdits`, no way to answer a prompt): a Write to `.git/inspector/x/a.json`
was refused ("requires approval ... which is a sensitive file"); a Write to `.inspector-run/a.json` succeeded.
In an interactive session that class of write is a permission prompt (inferred from the refusal text; not run
interactively), one per agent write. The collector itself (a script run by Bash) can still write under `.git/`; only the
agents' Write tool is affected. If the working tree is not writable the collector falls back to
`.git/inspector/<time>/`, then to a temporary folder; the agents' files may then need approval, or the
run works from the commands' output.

**Session scratchpad.** Hook payloads carry an optional `scratchpad_dir` common input field (present only
when the host provides a scratchpad; it is in the hook payload, which a script run by Bash never receives).
It is not the default: it is absent in some sessions, and the collector cannot read it. When the main
conversation's instructions name a scratchpad, pass `--out <scratchpad>/inspector-<time>` and the whole run
uses it. Not verified: that agents' Writes there never ask for approval in an interactive session.

**Same `where`, and no leads.** Two leads with one `where` are refused by `merge_verdicts.py`: give each a distinct suffix ` [lead N]` (a space, `[lead `, a number, `]`) on its `where` and in its verdict. The release gate compares on the `where` without the suffix and fails when a suffixed `where` repeats. With no lead at all, run `merge_verdicts.py` without `--verdicts` (`merged.json` is `[]`) and `handoff.py` (the "no leads" placeholder) so the folder still holds both files the gate requires; the generated plan lists both commands.
