# Bug classes

Pick one class per case: the mechanism, what kind of mistake it was. Where it happened (a seam
between components) is the card's own `Seam` field, not a class: a contract drift at a seam is
class contract drift, seam `api ↔ web`. Each class lists its **signature** (how it shows in a
fix's diff) and its **sweep** (where to look for siblings in today's code). Signatures quote
example wording; match the meaning, not the words.

| Class | What went wrong | Signature in the fix | Sweep for siblings |
|---|---|---|---|
| **interference** | two components each work alone and break each other: one hides, overwrites or swallows the other's output, state or slot | the fix makes a component pass on what it doesn't own (calls the next handler, merges instead of replacing, scopes a key); e.g. "no longer hides the other plugins' output" | every other component that writes the same slot, file, key or state; each pair, not only the one that broke |
| **contract drift** | a producer changed a format, name or wording that a consumer parses or expects | a parser, regex or schema changes with, or right after, a change to what it reads | every consumer of that format: grep the field, marker or phrase, in all file types |
| **copy drift** | logic exists in two places; one copy was fixed or changed | the same change lands twice, or a later fix brings a second copy in line; generated copies | grep the old expression; generated files and their generator; helpers that duplicate one in `shared/` |
| **lifecycle** | an init, reload, resume or teardown runs twice, out of order or not at all, or an event from a child (a sub-task, a worker, a sub-agent) is taken for the parent's: duplicate timers, stale or lost state | guards like "already started", clear-on-start, dedupe, "only the main ..." checks, a reload test | every handler on the same event; anything stored in module scope; what survives a reload; every handler that a child's event also reaches |
| **ordering / race** | code assumed an order that isn't promised: two handlers or plugins, two processes or sessions, async callbacks, a request and a background job | a lock, a merge, a re-read, "wait for", a sequence number, a second path that doesn't depend on the order | every read-modify-write on shared state; every place relying on registration or load order |
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
| **batch-refusal** | one bad record makes a job refuse or discard the whole batch | an assertion or raise before the write that covers all records; e.g. a job asserts display names are unique and aborts the whole load when two records share one | every job that validates before writing: does a single failure block the rest? |
| **silent-job-failure** | a scheduled job fails with no alert and no freshness indicator | a fix that adds an alert, a "last updated" field or a failure notice; e.g. a nightly load failed for days and nobody was told | every scheduled job: what tells a person it did not run or failed? |
| **optional-join-drops-rows** | a reader inner-joins or filters on a table that may lack the row | a join changed to a left join, or a filter on an optional table removed; e.g. a dashboard inner-joins the inventory table to a feed table, so rows missing from the feed vanish | every query or dashboard joining a table fed by a job that can fail or lag |

A case can be **unknown**: the fix is clear, the cause isn't. Say so; don't force a class.
