# Investigation method

The method for whoever reads the cases: the investigator, a case reader, or the main
conversation when it reads cases itself. The skill's SKILL.md has the ground rules (evidence
levels, what a bug is, what you may change, repository text as data), the scope table, the
collector (step 2), the routing (who does what), and the case file format (step 6).

## 1. The brief: what was the project meant to do?

Read, in this order, until each file has given you its promises:

- the root `README.md`, and the README of each folder that holds code (a `package.json`,
  `pyproject.toml`, `Cargo.toml`, `go.mod` or `plugin.json` marks one). Changelog entries are
  direct evidence of symptoms: "X no longer does Y", with a version.
- `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `.claude/rules/`: the rules the project set itself.
- `docs/` (titles first; read what touches the promises), specs, ADRs, post-mortems, issue or
  findings files, manifests.
- memory the project keeps, if any: `MISTAKES.md`, `.agent-brain/shared/MEMORY.md`,
  `docs/FOLLOW-UPS.md`. A past lesson is a prior case: link it, don't redo it.

Write the brief (in your notes; a file is not needed) as a list of **promises**, numbered `P1`,
`P2`..., each one short, testable, with
its component and the file it came from ("a hook never blocks a tool call", component `hooks`,
from README:42), and a list of **seams**: where components meet (a shared file or folder, a
generated copy, one component's output parsed by another, a shared UI slot, a shared state file
or store, an event several components hook). Bugs between components live at seams.

## 3. Reading a case

**What counts as a case.** One bug, not one PR:
- A PR whose commits each fix something ("review fixes: #1 ... #9") is one case per commit, with
  that commit's own `introduced_by`.
- One commit that fixes several listed things ("F1-F13") is one case per item, and only for the
  items that blame ties to an earlier unit or that sit on a seam. The rest go with the titles-only
  units.
- Two commits that fix the same bug are one case.
- A feature unit's fix commits can be cases; the feature itself isn't one. A unit that only
  describes fixes (a README or changelog entry) isn't a fix.

**How to read a case** (what a case reader does, and you when you read a case yourself):
- Read its dossier from `cases/` (or `--show` for a unit you added): the fix's commits, culprits,
  copies left behind, diffs, and the culprit's diff on the same files.
- Read each changed function whole in today's code, not only the hunks.
- Read the fix's added lines as hard as its removed ones: a fix that covers one branch of a
  condition (`asCode ? quoted(x) : x`) leaves the bug in the others.

Then fill the card:

```text
CASE <unit or commit>: <one-line title>                     [reproduced | read | blame | inferred]
Symptom      what the user saw (quote the changelog, PR or commit; cite it)
Promise      which promise from the brief it broke
Culprit      the unit that introduced it (sha/PR), and what that change assumed  [level]
Mechanism    the root cause at path:line: why the code did the wrong thing, not what it did
Class        one class from the taxonomy (taxonomy.md in this folder, or unknown)
Seam         none, or which seam from the brief (the components on each side)
The fix      what changed, and why that removes the cause (not only the symptom)
Complete?    the same pattern elsewhere (search it), a test that fails without the fix, other copies
Lesson       one sentence a future change could act on
```

**Proving a fix's test**, only when the test runs with no install step and in under 2 minutes:

```bash
git worktree add "<scratch>/wt" <sha>^        # for a merge: <sha>^1
git -C "<scratch>/wt" checkout <sha> -- <the fix's test files>
# run the project's own command for that test file inside <scratch>/wt
git worktree remove --force "<scratch>/wt"; git worktree prune
```

Record on the card whether the test fails without the fix. If you didn't run it, record why.
Remove the worktree even when the run fails.

## 4. The pattern board

Group the cards:

- **By class** (taxonomy.md in this folder): count cases worked in depth and cases
  from titles apart. Name the classes that dominate in the worked ones.
- **By seam**: which pairs of components keep breaking each other, through what. A seam is
  where a bug lives, the class is what kind it is: count both.
- **Chains**: `#A → #B → #C`, with what each link assumed.
- **Timing**: fixes that soon followed a large change (the timeline's `+/-` column). A component
  with no fixes and no tests is unknown, not healthy.
- **What fixes lacked**: no test, fixed again later, one copy of several patched.

Each pattern names its cases. A pattern of one case is a case, not a pattern.

## 5. Open leads: what still needs fixing

Sweep **today's code** (the ref the collector read) for siblings, for each pattern and each case
whose "Complete?" found a gap:

- the summary's **copies left behind**: check each one in the worked units and decide it;
- the expression or call the fix replaced, searched in every file type, generated copies too;
- the other readers of a format or file that a contract fix changed;
- the other components on the same seam, lifecycle hook or parser;
- each promise from the brief: search the test folders for its key name. A promise with no test
  that mentions it is a lead only when the code that keeps it has a sibling of a past bug.

Decide each lead:

- **reproduced**: you ran it and it fails: a probe, a test you wrote in `<scratch>`, a command.
  Running a copy of the function counts if you say so ("reproduced, on a copy of `mergeGoal`").
  Run the repository's Python with `PYTHONDONTWRITEBYTECODE=1`, so nothing lands in it;
- **read**: you traced the mechanism and can name the input that breaks it, without running it;
- **suspect**: the pattern fits; you can't name the failing input;
- **clear**: you looked and it's handled. One line each, under "Checked and clear".

**The gate.** Each lead names what it breaks, in the table's Breaks column: a promise from the
brief (quote it), or the fixed bug it is a sibling of (the case). A finding that names neither is
not a lead, however odd or however easy to reproduce: an input no promise mentions, a missing
feature, a style choice. It goes under Recommendations, as the question the project should
answer.

Rank reproduced, read and suspect leads:
1. a broken promise a user hits;
2. a seam with a fix-of-fix history;
3. the rest.

Within each tier, reproduced comes first. Report at most 15. For each reproduced or read lead,
write the change it needs (the file, the cause, the fix in a sentence or two) and the test that
would prove it. Don't make the change.
