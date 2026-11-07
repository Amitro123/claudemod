# What a test can and can't show

A lead's test is only useful if it can be written in the project's own test harness and fails
without the fix. Before proposing one, check it against the limits below and against the harness
the brief names (the README's "Developing" or "Testing" section, CONTRIBUTING, the CI workflow).
When the test you'd want can't be written there, say so and propose what can be checked instead.

Each test is one of:

- **automated**: a test in the project's harness that fails without the fix;
- **function-level**: a test of the pure function under the hook or handler (the parser, the
  merge, the decision), with the hard part given as input: two states for a race, a thrown error
  as a rejected promise passed in;
- **manual**: steps a person runs once, with what they should see. Use this when neither of the
  others can reach the bug, and say why (`why_not_automated`).

## Claude Code mods (`claude plugin test`)

Confirmed on this repository's mods:

- **A hook that throws is skipped; it doesn't fail the call.** The engine passes the event on
  without it. So "when X throws, the call is refused" can't be shown by making X throw in the
  test. Test the decision as a function, or check by hand.
  Source: the factory's #10 fix (`docs/inspector/2026-11-06-open-bugs.md`, Status); the engine
  reference, "A hook that fails is skipped and the chain continues without it".
- **Hooks run one after another.** Two sessions, or two hooks, can't be interleaved, so a race
  (two read-merge-write saves crossing) can't be reproduced. Test the merge with the two states
  the race would produce (function-level), or a store mock whose second read returns a newer copy.
  Source: task-hud 0.2.7 ("the test engine runs the hooks in turn, so the race the review named
  didn't reproduce"), and the read-merge-read-write fixes #5, #9, #12.
- **The order of plugins in a test is fixed.** A bug that depends on which mod's hook runs first
  is tested one path at a time: the `tool.call` path where the other mod sits beneath, and the
  `classic.PostToolUse` path alone for the other order.
- **No model runs in a test.** What a model does with a prompt or a skill is an eval
  (`claude plugin eval`), paid and not in CI, not a test.

## Anywhere

- **Timing**: a test that depends on how long something takes is flaky; inject the clock.
- **The platform**: a Windows path, another shell or an older runtime can't be shown on the CI
  machine unless CI runs it. Say which platform the test needs.
- **The network and external services**: mock them, or the check is manual.
- **The host's behaviour** (what an engine, a framework or an API does in a case): a test can
  only show the project's own code. When the impact rests on the host, cite where its behaviour
  is written, or mark the impact unverified.
