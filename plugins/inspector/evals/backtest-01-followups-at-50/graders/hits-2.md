---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 2
---

The answer key: bugs in plugins/followups (and the shared texts it uses) that existed in this repository and were fixed later.
K1. The CLAUDE.md export puts an item's `where` in backticks without quoted(), so a backtick or newline in it ends the code span.
K2. The docs/FOLLOW-UPS.md and README.md exports write item text as prose, not quoted as code (only CLAUDE.md quotes).
K3. The done tool marks any item done (also by title), not only one that was started (in progress).
K4. A saved entry that is not an item (null, no id or title) makes the session start fail instead of being dropped.
K5. The Hebrew stop phrase "פער" (an everyday word) stops turns needlessly.
K6. The stop check is cancelled when another hook blocked first (stop_hook_active), instead of keeping its own once-a-turn flag.
K7. Offering a sub-agent's open questions turns the end-of-turn stop check off.
K8. save() reads the store once, merges and writes: another session's save in between is lost.
K9. After an open-questions heading in a report, every non-blank line becomes an offered item (a VERDICT line, prose).
K10. A sub-agent's flag silences the main answer's loose-end check, or opens a question dialog in the middle of its run.
K11. Text typed under "Other" in the question is not kept as one line, and is added again when already listed or turned down.
K12. The Start line puts the item's detail and where unquoted, so model text reads as instructions and a newline or "[where:" corrupts parsing.
K13. followups checks for the factory only at session start, so when the factory starts after it the 🏭 buttons never show.
Also real (not fixed later): a done note with a line break is not parsed (doneResult/parseDoneResult).

PASS if at least 2 of the case file's open leads (reproduced, read or suspect) each match a different bug in the key (same code and same mechanism; wording may differ). FAIL otherwise. Say which key items matched.
