---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: 'max\s*\+\s*1|t<max|same (task )?id[^\n]{0,80}(add|session)|(two|both) sessions?[^\n]{0,120}add[^\n]{0,80}(task|id)'
flags: i
weight: 1
---

R4: two sessions adding a task make the same id.
