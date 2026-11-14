# claudemod

## Before a pull request is merged

Run the inspector's pre-merge check on the branch and post its output, unchanged, as a comment on the PR:

```bash
python3 plugins/inspector/skills/inspect/scripts/premerge.py --repo . --base origin/main --title "<PR title>"
```

It is passive. Its yes answers are reasons to look, not findings: don't change code, rerun an investigation or
hold the merge because of a flag alone. If reading the flag shows a real problem, fix it in the same PR. Either
way, add a row to the table in `plugins/inspector/evals/premerge/README.md` (the flag, and whether it was worth
changing something), which is how the check is measured.
