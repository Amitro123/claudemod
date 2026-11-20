# claudemod

## Before a pull request is merged

[review] Run the inspector's pre-merge check on the branch and post its output, unchanged, as a comment on the
PR:

```bash
python3 plugins/inspector/skills/inspect/scripts/premerge.py --repo . --base origin/main --title "<PR title>"
```

It is passive. Its yes answers are reasons to look, not findings: don't change code, rerun an investigation or
hold the merge because of a flag alone. If reading the flag shows a real problem, fix it in the same PR. Either
way, add a row to the table in `plugins/inspector/evals/premerge/README.md` (the flag, and whether it was worth
changing something), which is how the check is measured.

## How each rule below is held

Each rule is marked:
- **[CI]**: a workflow runs it on every pull request. `main` is not protected, so a red run shows but does not
  block a merge. Making it block is a repository setting (Settings, Branches, required status checks).
- **[review]**: the author shows the evidence in the PR and the reviewer checks it.
- **[advisory]**: a habit nothing checks yet.

## Fixing a bug

1. **[review] The broken invariant.** Say what the code assumed or promised that the report shows false. This
   names the kind of bug, which the tests then follow.
2. **[review] A regression test that fails first.** Reproduce the reported failure as a test, and show it
   failing on the code before the fix (the command and its output, in the PR). A test that passes on the old
   code proves nothing about the fix.
3. **[review] A few related boundary cases, each with a reason.** Pick the neighbours the invariant points to:
   - other settings, versions or shapes of the same input;
   - an empty, cut-off or escaped value;
   - another platform's form of the same thing.

   Add them to a table where one exists (`plugins/inspector/tests/test_scan_matrix.py` is the model). Say why
   each was chosen, and don't claim the table covers every variant: it covers the ones named.
4. **[advisory] Fixtures from real output.** Code that parses another program's output (git, gh, az, a
   transcript, a report) is tested against output that program really printed, saved as a fixture, where one
   can be had.
5. **[CI] The tests run in CI.** A regression test lives in a suite a workflow runs (`mods.yml` for the mods,
   `inspector.yml` for inspector and retro). A test only run by hand isn't a regression test.

## Pull requests

- **[advisory] One change per PR.** A group of related fixes is one PR; a release is its own PR. Past about 800
  changed lines (tests and docs aside), split it.
- **[review] A review says what it covered.** A review whose input was cut is not a complete review. The
  pre-merge check prints `the diff was cut at 40k characters` when it was. Such a review says which part it
  read; the rest gets its own review, or the PR is split.
- **[review] The reviewed commit and the evidence.** A review records the commit it reviewed (its SHA) and what
  it ran: the commands, and how many tests passed or which reproduction it tried. A push after the review makes
  that review about an older commit; say so, or review again.
- **[review] Run it on hard inputs before the merge** when the change reads another program's output, masks
  secrets, or decides what is allowed. The review builds a scratch repository or a fixture and runs the change
  on it; reading the diff alone isn't enough. What matters is independent reasoning and evidence someone can
  run; a reviewer from another model family is welcome, not required.
- **[review] What a reviewer didn't check stays open.** A NOT CHECKED item that touches the change is checked,
  turned into a test, or listed in `docs/open-items.md`. The factory records its own reviewers' items in
  `.factory/not-checked.jsonl` [CI-tested], but deciding what happens to each is review.
- **[review] No session links.** Commit messages and PR descriptions in this public repository carry no
  `Claude-Session:` line and no `claude.ai/code/session_` link. The factory takes them out of its own builder's
  commits [CI-tested]; any other commit is the author's to check.
