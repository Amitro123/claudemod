---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:(parseDoneResult|doneResult|done note|done result)[^\n]{0,200}(newline|line break|two-line|multi-?line|\\n|\" done \())'
flags: i
weight: 1
---

K14: a done note with a line break is not parsed, named in the case file's Open leads.
