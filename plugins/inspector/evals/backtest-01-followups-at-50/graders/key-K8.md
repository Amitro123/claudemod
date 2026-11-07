---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:save\(\)[^\n]{0,200}(race|lock|atomic|another session|concurrent)|(get|read)[^\n]{0,20}(→|->|then)[^\n]{0,20}merge[^\n]{0,30}(→|->|then)[^\n]{0,20}(set|write))'
flags: i
weight: 1
---

K8: save() race between sessions, named in the case file's Open leads.
