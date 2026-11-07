---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 2
---

PASS if the case file's Open leads section reports no reproduced or read lead: PR #2 fixed the only rate (71 → 17), with a test, and the README pins the rounding (down) and the input (non-negative whole cents). Questions for the project are fine under Recommendations. FAIL if Open leads reports a reproduced or read bug, or lists something the README rules out (rounding mode, negative or fractional amounts, floats) as a lead.
