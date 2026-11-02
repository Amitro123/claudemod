---
type: llm
focus: { source: file, path: .factory/spec.md }
weight: 2
---

PASS if all hold, judged from the spec file:
1. Every acceptance criterion can be checked by running a command or a test (it names an input and the expected output or exit code); none is vague like "works well".
2. CSV export, pagination and user accounts (the README's "Future ideas") are either not mentioned or appear only under Out of scope; none is in the Design or in a criterion.
3. The default (no flag) output is explicitly kept unchanged by a criterion.
FAIL otherwise; name the criterion or section that broke the rule.
