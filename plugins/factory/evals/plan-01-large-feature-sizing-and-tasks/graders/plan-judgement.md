---
type: llm
focus: { source: file, path: .factory/spec.md }
weight: 2
---

PASS if the spec file (a) states how passwords are stored (hashed, not plain text) and where the account file lives, and (b) lists a failure mode for a wrong password or unknown user. (Task sizing is checked by other graders; ignore TASKS.) FAIL otherwise; say which of a, b failed.
