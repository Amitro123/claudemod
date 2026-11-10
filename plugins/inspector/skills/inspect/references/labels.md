# Lead labels (the single source)

SKILL.md step 5, `agents/case-reader.md`, `agents/investigator.md` and `references/case-file.md` point here. Each carries only its schema's field list.

## category

`security`, `broken-flow`, `hardening`, `cost` or `other`.

`security` needs a documented or code-traced path from an input an outsider or another system controls to a sensitive sink (a secret persisted or sent on, a guard bypassed, injection); it is `traced` even when the real-world trigger was not observed. Name the input, the boundary, the sink and the actor, one line each, as `security_input`, `security_boundary`, `security_sink` (a path:line where possible) and `security_actor`. All four are required for security; a lead that cannot fill them is not security.

- The boundary must be one the actor could not already cross (the path gives them access, data, or influence over a sensitive sink they did not have); a path that only repeats access the actor already holds is `broken-flow`, not security.
- `security_actor` is a named party other than the repository owner or its maintainers who controls the input: a third party, a vendor or API response, an end user, another tenant, an outside PR author, or a model reading content that an outsider can write. Text from the owner's own repository read by the owner's own model is not adversarial unless an outsider can write it (say how). A lead that cannot name such an actor is `broken-flow` or `hardening`, not security.
- A filled-in input, boundary and sink are not enough: the boundary has to be one this actor was kept out of.
- Security counter-argument: before a lead is emitted as `security`, write `security_counter`, the strongest one-line argument that it is only `hardening` or `broken-flow` (for example: the actor already has this access; the output never reaches the actor; the input is the owner's own). The lead stays `security` only if a named fact refutes the counter (a path:line, a doc line or a probe), written in `security_counter_refuted_by`. handoff.py prints both next to the quadruple and warns on stderr when either is missing.

## needs-host-check, change_status

A claim whose truth depends on host or runtime behaviour not observed in this session: impact level `unverified` and the flag `needs-host-check`. It says what would confirm it; it flags that the trigger or the sink's behaviour in the real environment was not observed, and it never changes the category.

`change_status` `verified` | `unverified`: `unverified` when the change depends on host or tool semantics nobody observed (a variable format that doubles quotes the query already adds); the change line then says what to verify first. A proposed change or test that contains a query (KQL, SQL, a log query) stays `unverified` until the query was parsed or run read-only, and the lead carries the exact read-only command that would do it. `lint_leads.py` rule L9 warns on a `verified` change that contains a query unless the lead has evidence of a completed read-only run with an observed result. Preferred, structured: `query_run: {"mode": "read-only", "status": "executed", "observed": "<result summary>"}`, written only by whoever ran the query. Free text is accepted only as a completed statement with a result (`ran the query read-only; returned 12 rows`); negation (not executed, was not, unavailable, could not, cannot, no access) and instructions or conditions (run this, to be run, after deployment, should, will, must, before) never count. L9 is advisory text matching, not proof of execution.

## reach

`reach` is how a lead is triggered:

- `default-on`: the default configuration with normal inputs triggers it.
- `conditional`: needs a named condition (output-format drift, a rare input, a race, a specific platform).
- `opt-in`: needs a flag or setting that is off by default.
- `unknown`: not traced.

`reach_when` (optional): short text for `conditional` and `opt-in` (`format drift`, `flag defaults off`). A bug that only fires when a model's output format drifts is `conditional`, never `default-on`. A missing `reach` is shown as `unknown`.

## Traced claims only

Every factual sub-claim in a lead's `what` (for example "also after reload", "fails for format X") must have been traced or run. An untraced sub-claim is dropped from `what` or moved to `not_verified` (optional list of short strings). `not_verified` is printed under the impact and never counts as a level.

## probe

A lead at level `reproduced` or `read` carries `probe`: the exact input and output, or the command run, or the path:line read, in one line. For a headline claim about an external tool or format (a CLI flag, an escape format, a template), the probe is the command that checked it (for example the tool's `--help`). A headline claim with no probe goes to `not_verified`. handoff.py prints `probe: ...` under the impact and warns on stderr when a `reproduced` or `read` lead has none.

## test_kind, downstream

`test_kind` names what the proposed `test` is: `behavioral` (fails on the unfixed code by exercising behaviour), `text-pin` (asserts that text or config is present), `manual` (needs a live environment; say which). Prefer behavioral; a text-pin test is acceptable only next to a behavioral one or when no behaviour can be exercised. A test of a query is `manual` or `behavioral`, never `text-pin` alone (a query can be run). handoff.py prints `[test: kind]` and marks `text-pin` as `[weak: pins text only]`; a missing kind prints `[test: unknown]`.

`downstream` (optional, one line): what else the proposed change changes, or what could still fail after it (for example: renewing expired exceptions still fails the gate on new vulnerabilities). Printed as `downstream: ...` under the change.

## allowlists and sets

A lead about one member of an allowlist, schema or set names every member and how many were checked (`1 of 8`).

## reconcile

`reconcile` (optional, one line): the check against the source of truth for a lead whose mechanism is a pipeline's data being wrong, missing or stale. Printed as `reconcile: ...` under the impact. How to write the check: references/reconcile.md.

## documented, observed_in_production

`documented` (optional, short string): where the behaviour is documented or test-pinned (a doc line, a test name); empty or absent if not. `observed_in_production` (optional): `yes` | `no` | `unknown`, plus `observed_source` (where it was seen). When `documented` is set, the category stays what it is, but the lead's text says so, its severity is not set from code alone (a documented, test-pinned behaviour can still do harm in production), and it carries a `reconcile` (or `probe`) naming the production evidence that would show harm (a freshness query, a reconciliation, a job history). handoff.py prints `documented: ...` under the impact and `[production: yes|no|unknown]` next to the level (missing is `unknown`); `yes` sorts first, even above a higher-level lead whose production state is unknown or `no`; inside the same production state the order is level, then the reach order. When the project's own notes (the mistakes or incident file the method reads) record the failure as having happened in production, set `observed_in_production: yes` with that note as `observed_source`; such a lead is listed first. It warns on stderr when `documented` is set with neither `reconcile` nor `observed_in_production: yes`.
