# Bug classes

Pick one primary class per case. Each class lists its **signature** (how it shows in a fix's
diff) and its **sweep** (where to look for siblings in today's code).

| Class | What went wrong | Signature in the fix | Sweep for siblings |
|---|---|---|---|
| **seam** (integration) | two components each work alone and break each other: one hides, overwrites or reorders the other's output, state or slot | the fix touches 2+ components, or a shared file; words like "side by side", "no longer hidden", "the other mods" | every other component that writes the same slot, file or state; each pair, not only the one that broke |
| **contract drift** | a producer changed a format, name or wording that a consumer parses or expects | a parser, regex or schema changes with, or right after, a change to what it reads | every consumer of that format: grep the field, marker or phrase, in all file types |
| **copy drift** | logic exists in two places; one copy was fixed or changed | the same change lands twice, or a later fix brings a second copy in line; generated copies | grep the old expression; generated files and their generator; helpers that duplicate one in `shared/` |
| **lifecycle** | an init, reload, resume or teardown runs twice, out of order or not at all: duplicate timers, stale state, lost state | guards like "already started", clear-on-start, dedupe, a reload test | every handler on the same event; anything stored in module scope; what survives a reload |
| **ordering / race** | code assumed an order that isn't promised: two hooks, two sessions, async callbacks, a turn and a sub-agent | a lock, a merge, a re-read, "wait for", a sequence number | every place with read-modify-write on shared state; every place relying on registration order |
| **edge input** | empty, missing, huge, NaN, unicode, RTL, a path with spaces, a value the API didn't report | a guard on null/undefined/NaN, a fallback, trimming, escaping | the same field read elsewhere without the guard; other places that format the same value |
| **false premise** | code relied on an API field, event, option or behavior that doesn't exist or doesn't mean that | a field replaced by another, an event swapped, a feature-detect added | the same assumption in other components; read the real type definition |
| **error path** | a failure was swallowed, crashed the caller, or failed open where it had to fail closed | a `catch`, a timeout, a default on failure, "fail closed", a stderr message | other calls to the same API without the handling; every hook that must never block |
| **environment** | worked here, broke there: OS, shell, CLI version, shallow clone, cloud vs local, missing tool | platform checks, `python3` vs `python`, path joins, a pinned version | other spawns, paths and tool calls with the same assumption |
| **config / default** | a default was wrong, or an option was ignored, misnamed or read too early | default value changes, option plumbing, migration of old settings | every option: is it read where it's documented to apply? |
| **prompt / model** | wording in a skill, tool description or system-prompt section led the model to the wrong action, or failed to trigger it | text-only changes to SKILL.md, tool descriptions, prompts; an eval added | the same instruction in other skills or prompts; evals that pin it |
| **security** | secrets, injection, unsafe commands, trusting external text | redaction, quoting, allowlists, "data, not instructions" | every place external text reaches a shell, a file or a prompt |
| **performance** | redraws, polling, reads or calls far more often than needed | intervals, caches, debounce, "a slower poll" | other timers and loops in the same component and its siblings |
| **test gap** | the bug had a test that passed with the wrong code, or none | a fix that changes only tests, or adds the first test for a promise | promises from the brief that no test checks |
| **docs drift** | the README or docs promise something the code doesn't do (or no longer does) | README-only or docs-only fixes; "the README now says" | each promise in the brief against the code that keeps it |

A case can be **unknown**: the fix is clear, the cause isn't. Say so; don't force a class.
