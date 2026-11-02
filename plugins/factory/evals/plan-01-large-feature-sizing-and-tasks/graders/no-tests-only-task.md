---
type: regex
pattern: '^\s*\d+\.\s+\[[a-z]+\]\s+(write|add|create)\s+(unit\s+|integration\s+)?tests?\b[^\n]*$'
flags: im
match: not_contains
weight: 2
---
