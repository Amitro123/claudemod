---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:(startLine|Start (line|prompt))[^\n]{0,200}(detail|where))'
flags: i
weight: 1
---

K12: Start line leaves detail and where unquoted, named in the case file's Open leads.
