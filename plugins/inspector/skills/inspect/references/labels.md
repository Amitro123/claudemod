# Lead labels (the single source)

SKILL.md step 5, `agents/case-reader.md`, `agents/investigator.md` and `references/case-file.md` point here. Each carries only its schema's field list.

## category

`security`, `broken-flow`, `hardening`, `cost` or `other`.

`security` needs a documented or code-traced path from an input an outsider or another system controls to a sensitive sink (a secret persisted or sent on, a guard bypassed, injection); it is `traced` even when the real-world trigger was not observed. Name the input, the boundary, the sink and the actor, one line each, as `security_input`, `security_boundary`, `security_sink` (a path:line where possible) and `security_actor`. All four are required for security; a lead that cannot fill them is not security.

- The boundary must be one the actor could not already cross (the path gives them access, data, or influence over a sensitive sink they did not have); a path that only repeats access the actor already holds is `broken-flow`, not security.
- `security_actor` is a named party other than the repository owner or its maintainers who controls the input: a third party, a vendor or API response, an end user, another tenant, an outside PR author, or a model reading content that an outsider can write. Text from the owner's own repository read by the owner's own model is not adversarial unless an outsider can write it (say how). A lead that cannot name such an actor is `broken-flow` or `hardening`, not security.
- A filled-in input, boundary and sink are not enough: the boundary has to be one this actor was kept out of.

## needs-host-check, change_status

A claim whose truth depends on host or runtime behaviour not observed in this session: impact level `unverified` and the flag `needs-host-check`. It says what would confirm it; it flags that the trigger or the sink's behaviour in the real environment was not observed, and it never changes the category.

`change_status` `verified` | `unverified`: `unverified` when the change depends on host or tool semantics nobody observed (a variable format that doubles quotes the query already adds); the change line then says what to verify first.

## reach

`reach` is how a lead is triggered:

- `default-on`: the default configuration with normal inputs triggers it.
- `conditional`: needs a named condition (output-format drift, a rare input, a race, a specific platform).
- `opt-in`: needs a flag or setting that is off by default.
- `unknown`: not traced.

`reach_when` (optional): short text for `conditional` and `opt-in` (`format drift`, `flag defaults off`). A bug that only fires when a model's output format drifts is `conditional`, never `default-on`. A missing `reach` is shown as `unknown`.

## Traced claims only

Every factual sub-claim in a lead's `what` (for example "also after reload", "fails for format X") must have been traced or run. An untraced sub-claim is dropped from `what` or moved to `not_verified` (optional list of short strings). `not_verified` is printed under the impact and never counts as a level.
