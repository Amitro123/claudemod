---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: '^\|\s*\w*\d+\s*\|\s*(reproduced|read)\b'
flags: im
match: not_contains
weight: 2
---
