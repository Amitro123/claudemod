---
type: regex
pattern: '(acceptance criteria|required behaviou?r|acceptance tests)[\s\S]*?\n\s*1[.)]\s+\S[\s\S]*?\n\s*2[.)]\s+\S'
target: { source: file, path: .factory/spec.md }
flags: i
weight: 2
---
