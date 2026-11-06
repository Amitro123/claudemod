---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 2
---

PASS if the case file says PR #8's bug (cents dropped) was introduced by PR #6, itself a fix (it added int() when it removed the double discount), i.e. a fix of a fix. FAIL if it doesn't connect #8 to #6.
