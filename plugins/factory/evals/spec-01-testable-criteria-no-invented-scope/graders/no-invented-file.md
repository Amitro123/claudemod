---
type: regex
pattern: 'src/shop/(export|accounts?|users?|paginat)\w*\.py'
target: { source: file, path: .factory/spec.md }
match: not_contains
weight: 2
---
