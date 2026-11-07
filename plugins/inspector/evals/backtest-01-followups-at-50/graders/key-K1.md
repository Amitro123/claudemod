---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:`?where`?[^\n]{0,200}(quoted\(\)|code span|backtick|unescaped|not escaped|raw))'
flags: i
weight: 1
---

K1: where unquoted in the CLAUDE.md export, named in the case file's Open leads.
