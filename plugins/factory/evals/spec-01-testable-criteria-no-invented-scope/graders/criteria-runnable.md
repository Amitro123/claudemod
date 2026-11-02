---
type: regex
pattern: '(unittest|python3? -m|json\.loads|exit code|returns? 2)'
target: { source: file, path: .factory/spec.md }
flags: i
weight: 1
---
