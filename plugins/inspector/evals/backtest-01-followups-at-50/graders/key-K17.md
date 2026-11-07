---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:sync\(\$?\)?[^\n]{0,120}(\.catch|no catch|without a catch))'
flags: i
weight: 1
---

K17: session.start's sync has no .catch, named in the case file's Open leads.
