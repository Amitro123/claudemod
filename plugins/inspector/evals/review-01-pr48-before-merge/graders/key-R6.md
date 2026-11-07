---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '(exclude|keepOutOfGit|journal)[^\n]{0,220}(retr|every (journal )?write|no git|git (is )?missing)'
flags: i
weight: 1
---

R6: the journal's exclude is retried at every write when there is no git.
