# RUN-1 NOTES (2026-11-01)

Result: no case produced a graded model run. Spend 0 USD.

1. First attempt (spec-01, code-01, appr-04, MAX_COST=2): both arms exit 1 in ~4s, turns=0, cost 0.
   Cause: run-all.sh grants `--allow-tools Bash Edit Write` to every case; WSL has bwrap but not socat,
   so Claude Code refused to run (sandbox.failIfUnavailable). The 0.13/0.00/0.22 scores come from graders
   run on an empty last_message; WITH==W/OUT is meaningless.
2. Fix: run-all.sh now honors `ALLOW_TOOLS=none` (drops the shell grant). Alternative: `sudo apt install socat`.
3. Retry (ALLOW_TOOLS=none): with-arm ended `401 User not found` (endpoint rejected the key); without arm not run.
   Needs a valid key in ~/.or-env.
4. Grader audit: not possible (no traces with model output). No graders changed.

## Run 2a (key fixed, ALLOW_TOOLS=none, MAX_COST=2) total spend 1.05 USD (spec-01 0.66, code-01 0.19, appr-04 0.19)
- code-01 with/without: 1.00/1.00 (all graders pass, delta 0). Not a validity problem: ablation Delta 0 means the base model already catches it.
- appr-04 with 1.00 (4 graders incl. skill-fired) / without 0.67: only reason-names-area fails without plugin (the area rule lives in the skill). Valid ablation signal.
- spec-01 (0.27 both arms) is a HARNESS defect, not a grader defect: 7 file graders threw "path .factory/spec.md does not exist".
  The spec cases declare no allowed_tools in case.yaml (README claims Write is declared; it is not), so with ALLOW_TOOLS=none the model could not Write. Fix: run-all.sh now accepts ALLOW_TOOLS="Edit Write" (no Bash, no socat needed). Re-run spec-01 that way (needs approval).
- Without-arm plugin absence: traces under /tmp were removed after the run, so not checked directly. Indirect evidence only: no skill-fired grader in without arm, and appr-04 without-arm lost the skill-only rule.
- Graders NOT changed: no regex was shown to be wrong. Weak spots (unverified): finding-on-utils needs a bullet format ^\s*[-*]\s*\[(blocker|major)\]; code-01 llm-judge unanimous PASS.

## Run 2b: spec-01 re-run (ALLOW_TOOLS="Edit Write", KEEP_TEMP=1), cost 0.44 USD (with 0.23, without 0.21)
- run-all.sh gained KEEP_TEMP=1 (adds --keep-temp). Note: it kept /tmp/claude-eval-*/out/trace.jsonl but the scaffold cwd/.factory/spec.md was gone; recover spec text from the Write call in the trace.
- WITH 1.00 (11/11 pass, incl. skill-fired, scope-judgement 3/3). WITHOUT 0.87: only criteria-numbered fails. Delta 0.13.
- Plugin evidence (trace init event): with arm plugins list has factory 0.12.0, skills/agents factory:spec-writer etc., tool mcp__factory__start, Skill factory:spec-writer called. Without arm: plugins only builtin cc-plugin-*, no factory skills/agents/commands/tools, no Skill call. Ablation is real.
- criteria-numbered (regex needs the literal phrase "acceptance criteria" then 1. and 2.): the without spec has numbered "Required behaviour" items and an "Acceptance tests" section, no "Acceptance criteria" heading. Fails for a heading-name reason, not for missing testable criteria; it is brittle but it measures the skill/prompt vocabulary, so left unchanged. Consider widening to (acceptance criteria|required behaviou?r|acceptance tests) if you want it to measure substance only.
- size-small, tasks-format, tasks-no-roadmap: pass for valid reasons (anchored on SIZE:/TASKS: lines in the answer; roadmap negative check works). No grader edited.

## Run 2c: all remaining model cases (ALLOW_TOOLS="Edit Write", KEEP_TEMP=1, MAX_COST=2) cost 1.79 USD; session total about 3.3 USD
Traces copied to evals/results/traces/<case>-<arm>-0.jsonl (/tmp is wiped by WSL restarts). Skipped (need Bash, wait for socat): build-01 (committed, tests-were-run), build-02 (no-cat-large-files, tests-were-run).
Scores with/without: appr-01 1/1, appr-02 0.86/0.86, appr-03 1/1, code-02 1/1, plan-01 0.85/0.85, sec-01 1/1, sec-02 0/0, spec-02 1/1.
Without-arm init check: no factory in plugins/skills/agents for every case above; with arm has it. Without arm even says "factory skill is not installed".
Fixes (no re-run):
- appr-02 reason-present: REASON:\s*\S{10,} needs 10 non-space chars in a row, so a normal sentence ("Adds `list --json` ...") failed in both arms. Now REASON:\s*\S[^
]{9,}. Expected score 1.0 both arms.
- plan-01 plan-judgement: unanimous FAIL in both arms; the rubric clause (c) referred to TASKS in the last message but the judge only sees the spec file, so (c) could never pass (also a 11.8k-char spec). Clause (c) dropped (task count is covered by tasks-3-to-8). Unverified that this flips it.
- spec-01 criteria-numbered: widened to also accept "required behaviour" / "acceptance tests". The old regex also required a blank-ish gap between item 1 and 2 (the newline after item 1 was consumed), so single-line numbered items never matched. New: (acceptance criteria|required behaviou?r|acceptance tests)[\s\S]*?
\s*1[.)]\s+\S[\s\S]*?
\s*2[.)]\s+\S. Checked offline on reconstructed with/without texts (match) and a spec with no numbered list (no match); the kept traces from run 2b had been wiped, so real texts were not used.
Not changed:
- sec-02 (clean-diff control): both arms CHANGES with [blocker] (users table defined nowhere but the test) and [major] (find_user returns pw_hash). The fixture is not clean (spec itself asks for pw_hash; schema absent from the diff). Grader is right, fixture is wrong; tell the user before editing the case.
Delta signal: real only for appr-04 (skill-only sensitive-area rule) and spec-01 (heading/format conventions, small). Zero delta on code-01, code-02, sec-01, appr-01/03, spec-02, plan-01: bare model already does it, and the prompts contain the rules.

## Run 3 (2026-11-02): sec-02 fixture rewrite + re-run of sec-02, appr-02, plan-01, spec-01. Cost 1.17 USD (0.21, 0.12, 0.49, 0.36); session total about 4.5 USD
- sec-02 fixture rewritten: SELECT id, name only, schema in app/db.py (init_db), spec covers token_ok and schema, token compare on bytes and None rejected. Offline: scaffold ok, 5 unittests OK, git apply -R --check change.diff ok (change.diff is now generated by git diff HEAD~1 HEAD). prompt.md file stat updated. FACTORY-SUITE.md has a note on what a bad reviewer would do.
- sec-02: 1.00 / 1.00, all graders pass in both arms. The false-positive control now passes; delta 0 (bare model is not a worse reviewer here).
- appr-02: 1.00 / 1.00. reason-present fix worked (matched REASON:\s*\S[^\n]{9,}).
- plan-01: with 1.00 (plan-judgement PASS 3/3, so dropping clause (c) worked), without 0.85: no-tests-only-task FAILS because its task 5 is "[medium] Write tests for accounts ..." a standalone tests task. Valid failure, real skill signal (delta 0.15). plan-judgement passes both arms now, as expected.
- spec-01: with 1.00; without 0.87: criteria-numbered now passes both arms (fix worked), but scope-judgement FAILS 3/3 in without (it passed in run 2b, so the without arm output varies); judge gives no reason in the json. Not edited; unverified whether failure is valid. Real delta 0.13 but only 1 run.
- Without-arm init event shows no factory plugin/skills/agents/tools in all four cases (traces in results/traces/run3-*).
