---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 3
---

PASS if the case file's open leads include to_docs (the docs/ export) still writing item titles unquoted, as the same bug PR #2 fixed only in to_claude_md, and name the change (quote them as to_claude_md does, e.g. with quoted()). FAIL if that lead is missing, or if to_csv's unquoted output is reported as a bug (the README says CSV is not read by agents).
