---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 3
---

PASS if an open lead says the space-separated form (`--password hunter2`, `--token abc`) still reaches the file unredacted, at level reproduced or read, and names the change (also match a flag followed by a space and a value). FAIL if the lead is missing, or only suspect with no input named.
