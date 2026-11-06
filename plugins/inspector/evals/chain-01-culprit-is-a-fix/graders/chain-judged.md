---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 2
---

PASS if the case file says PR #3's crash on None was introduced by PR #2, which was itself a fix (it rewrote total() and dropped the `if not items: return 0` guard), i.e. a fix of a fix. FAIL if it names #1 as the culprit of the crash, leaves the culprit unknown, or doesn't mention that #2 dropped the guard.
