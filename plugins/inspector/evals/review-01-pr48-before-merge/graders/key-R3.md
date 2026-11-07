---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '(re-?plan)[^\n]{0,220}(t1|ids?|merge|progress)|task ids?[^\n]{0,140}(restart|reuse|collide)'
flags: i
weight: 1
---

R3: a re-plan's task ids restart, so a merge mixes the old plan's progress in.
