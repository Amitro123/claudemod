---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '`?where`?[^\n]{0,200}(quoted|code span|backtick|unescaped|raw)|(docs|FOLLOW-UPS|README)[^\n]{0,160}(export)[^\n]{0,160}(raw|unquoted|not quoted|prose)|export[^\n]{0,80}(docs|README)[^\n]{0,160}(raw|unquoted|not quoted|prose)'
flags: i
weight: 1
---

R1: the export quotes only the CLAUDE.md target, or leaves where unquoted.
