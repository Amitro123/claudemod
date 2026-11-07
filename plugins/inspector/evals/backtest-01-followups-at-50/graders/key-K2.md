---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:(docs|FOLLOW-UPS|README)[^\n]{0,120}export[^\n]{0,160}(raw|unquoted|not quoted|prose|unescaped)|export[^\n]{0,60}(docs|README)[^\n]{0,160}(raw|unquoted|not quoted|prose|unescaped))'
flags: i
weight: 1
---

K2: docs and README exports unquoted, named in the case file's Open leads.
