---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '(redact|secret|password|token)[^\n]{0,220}(space|separated|--password \S|--token \S|flag followed|-p \S)'
flags: i
weight: 1
---

R2: space-separated secret flags are not redacted.
