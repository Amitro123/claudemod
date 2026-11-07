---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:followups:end|end marker|END marker|marker text)'
flags: i
weight: 1
---

K15: the export end marker inside an item, named in the case file's Open leads.
