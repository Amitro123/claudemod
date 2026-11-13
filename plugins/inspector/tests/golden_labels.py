"""The hand labels of this repository's history up to #72, from the 2026-11-06 investigation
(plugins/inspector/docs/2026-11-06-review.md). No imports: the golden test and the decision-model
experiment (evals/decision-fix) both read them, so there is one copy."""

PR72 = "92974e4"  # Merge pull request #72: the labels describe the history up to here

FIXES = "#6 #23 #27 #36 #38 #48 #50 #53 #54 #60 #66 #70 #71 #72".split()
# Hand-labeled fixes whose only machine evidence is a patch version bump: not a fix signal since the
# precision fix (PRs 113 and 123 of the model-router run were bump-only non-fixes). A known recall loss.
BUMP_ONLY_FIXES = "#18 #25".split()
NOT_FIXES = "#1 #2 #3 #4 #5 #17 #20 #21 #26 #29 #34 #37 #42 #44 #45 #58 #61 #65 #67 #68".split()
