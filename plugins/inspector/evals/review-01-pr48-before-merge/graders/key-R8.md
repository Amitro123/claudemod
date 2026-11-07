---
type: regex
target: { source: file, path: docs/inspector/case.md }
pattern: 'checks? question|(which|what) (commands|checks)[^\n]{0,80}(run|allow)|watch(es|ed)? (more )?files|approv[^\n]{0,80}checks?'
flags: i
weight: 1
---

R8: the checks question doesn't say what it lets run, or watches too few files.
