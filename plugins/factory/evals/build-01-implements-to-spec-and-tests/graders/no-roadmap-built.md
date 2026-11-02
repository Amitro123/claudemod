---
type: regex
pattern: 'csv|paginat'
target: { source: file, path: src/shop/cli.py }
flags: i
match: not_contains
weight: 2
---
