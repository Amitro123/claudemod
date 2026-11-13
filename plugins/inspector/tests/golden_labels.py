"""The hand labels of this repository's history up to #72, from the 2026-11-06 investigation
(plugins/inspector/docs/2026-11-06-review.md). No imports: the golden test and the decision-model
experiment (evals/decision-fix) both read them, so there is one copy."""

PR72 = "92974e4"  # Merge pull request #72: the labels describe the history up to here

FIXES = "#6 #23 #27 #36 #38 #48 #50 #53 #54 #60 #66 #70 #71 #72".split()
# Hand-labeled fixes whose only machine evidence is a patch version bump: not a fix signal since the
# precision fix (PRs 113 and 123 of the model-router run were bump-only non-fixes). A known recall loss.
BUMP_ONLY_FIXES = "#18 #25".split()
NOT_FIXES = "#1 #2 #3 #4 #5 #17 #20 #21 #26 #29 #34 #37 #42 #44 #45 #58 #61 #65 #67 #68".split()

# The history after #72 (#73-#123), labeled 2026-11-13 and confirmed by the owner. The regex was never
# tuned on these: they are the fair test of regex vs decision model (evals/decision-fix).
# Close calls: #82 #96 #101 fix (no "fix" in the title: a PASS with a major finding read as pass,
# one verdict applied to two leads, valid cards refused); #84 #122 mixed PRs with a real fix;
# #110 #115 fixes to skill instructions, not code. #85 is a feature ("fix evidence" in its title);
# #98's "Fixed" changelog lines belong to #97; #75 #100 #106 are redesigns or features.
PR123 = "dbf757a"  # Merge pull request #123: LATER_* describe the history up to here
LATER_FIXES = ("#74 #76 #77 #78 #81 #82 #84 #96 #97 #101 #104 #108 #110 #112 #113 #115 #119 #120 #122 "
               "#123").split()
LATER_NOT_FIXES = ("#73 #75 #85 #86 #87 #88 #89 #90 #91 #92 #93 #94 #95 #98 #99 #100 #102 #105 #106 #107 "
                   "#109 #111 #114 #116 #117 #118 #121").split()
