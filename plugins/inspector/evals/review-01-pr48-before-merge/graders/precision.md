---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 2
---

The answer key: bugs the branch pr48 (PR #48) introduced or left, found by the review after it merged:
R1 the export quotes only the CLAUDE.md target (docs and README exports keep prose), and `where` stays a raw code span;
R2 secret redaction covers --password=x and token: forms, not space-separated flags (--password foo, -p foo);
R3 a re-plan keeps setAt and restarts task ids at t1, so a merge puts the old plan's progress on the new tasks;
R4 two sessions adding a task both make t<max+1>, and the merge keeps one;
R5 an item sent to the factory is not recorded as started here, so the pane offers Start again;
R6 with no git to run, the journal's exclude is retried at every write;
R7 a task appended in a new turn retitles the band;
R8 the checks question doesn't say what it lets run, and watches too few files.

PASS if every finding the file presents as a bug in the branch, whatever its format or label, either matches the key or names a concrete input and the code path (file and function) that mishandles it. Findings plainly marked as unverified or suspect don't count against it. FAIL if a finding presented as a bug is a style or feature wish, is about code the branch doesn't touch and doesn't affect, or names no input.
