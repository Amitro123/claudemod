"""DRAFT hand labels for the history after #72 (#73-#123), not yet confirmed by the owner.
Labels the regex never saw: the fair test of regex vs decision model vs both.
Rule as in golden_labels.py: a fix repairs behaviour that shipped (including review fixes after merge);
a feature, docs, refactor, perf change or release is not. A mixed PR with a real fix counts as a fix."""

PR123 = "dbf757a"  # Merge pull request #123: these labels describe the history up to here

FIXES = ("#74 #76 #77 #78 #81 #82 #84 #96 #97 #101 #104 #108 #110 #112 #113 #115 #119 #120 #122 #123").split()
NOT_FIXES = ("#73 #75 #85 #86 #87 #88 #89 #90 #91 #92 #93 #94 #95 #98 #99 #100 #102 #105 #106 #107 #109 "
             "#111 #114 #116 #117 #118 #121").split()

# Borderline calls, for the owner to confirm: unit -> (draft label, why)
BORDERLINE = {
    "#82": (True, "parseVerdict read a PASS with a major finding as pass; skeptic matched duplicate findings to one ruling; module failed to load on older CLIs"),
    "#96": (True, "merge_verdicts silently applied one verdict to two leads with one where (INS-05); handoff --cards file path documented but broken"),
    "#101": (True, "cards with single-backslash regexes were invalid JSON and refused; CHANGELOG says Fixed"),
    "#84": (True, "mostly features, but carries the four collector precision fixes"),
    "#122": (True, "features plus fix(factory): credential in branch history passed; resume and BOM fixes"),
    "#110": (True, "instruction fix, not code: the run collapsed into one worker and ran serially"),
    "#115": (True, "instruction fix: verification could be skipped"),
    "#85": (False, "a feature (GitHub enrichment); the title says 'fix evidence', which trips the regex"),
    "#98": (False, "method rules; its CHANGELOG diff shows the #97 fixes, which belong to #97"),
    "#106": (False, "new duplicate flagging, lint rule and sort order: features, no broken behaviour repaired"),
    "#75": (False, "a redesign of the handoff; corrects one row of an earlier report, not code"),
    "#100": (False, "workflow change: agents write their own files"),
}

assert not set(FIXES) & set(NOT_FIXES)
assert all((u in FIXES) == lab for u, (lab, _) in BORDERLINE.items())
