---
type: llm
focus: { source: file, path: .factory/spec.md }
weight: 3
---

PASS if the spec's Design and tasks make the change in src/greeter/templates/hello.txt and then regenerate with tools/build_plugin.py, so plugins/greeter/templates/hello.txt changes only through the generator. A sentence such as "do not edit plugins/ by hand" is correct. FAIL if the spec tells the builder to edit plugins/greeter/templates/hello.txt directly (alone or as a separate manual step), or never says the generated copy must be regenerated.
