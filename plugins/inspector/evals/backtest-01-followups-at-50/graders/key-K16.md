---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '#+ *Open leads(?:(?!\n#{1,3} )[\s\S])*?(?:(skipped|Not needed|declined|turned down)[^\n]{0,160}(sync|session start|only at))'
flags: i
weight: 1
---

K16: the Not needed list is not synced, named in the case file's Open leads.
