# Spec: the factory's issue queue and PR step over GitHub REST (issue #152)

## Problem

The factory's GitHub-issue queue runs `gh issue list`, `gh issue view`, `gh issue comment`, `gh label create`
and `gh issue edit` (`plugins/factory/hooks/register.tsx:1286-1362`), and the PR prompt tells the main Claude
to open the PR with `gh pr create` and, with `autoMerge` on, to merge with `gh pr merge`
(`plugins/factory/hooks/flow.ts:556-577`). All of these go through GitHub's GraphQL API, which Claude Code
cloud sessions refuse (`403 ... GitHub GraphQL is not available from Claude Code sessions; use the REST API`).
So in a cloud session `/factory run` and `/factory queue` can't read the queue, the factory can't comment on
or label an issue, and the PR commands it hands out fail. The REST API (`gh api repos/...`) works in the same
session. This affects everyone running the factory on GitHub issues from a cloud session.

## Scope

In:

- The five issue operations the hooks run (list, view with comments, comment, label create, label add/remove)
  move to `gh api` REST calls. **Replace, not fall back**: REST works wherever gh works, so one code path, no
  GraphQL-refusal detection.
- New REST parsers in `plugins/factory/hooks/issues.ts` that map GitHub's REST JSON onto the existing `Issue`
  type, and keep the trust boundary exactly as it is: the open + `factory`-label check (`refusal`) and the
  author/operator-only comment filter (`trustedComments`). Pull requests are left out of the issue list and
  refused by number; comments are paged in full.
- The PR step: `prCommands` and `prPrompt` give the PR creation and the autoMerge merge as `gh api` REST calls.
- Tests for the REST shape of each call, and the test engine's gh mock moved to REST.
- The user-facing text that names `gh pr create` / `gh pr merge` (README, plugin.json option description).

Out of scope:

- `/factory doctor` reporting that the session refuses GraphQL (in the issue's acceptance list, left out by the
  intake). `doctorText` (`register.tsx:1658-1705`) is not changed.
- A GraphQL path or fallback; detecting cloud sessions.
- The operator lookup `gh api user --jq .login` (`register.tsx:1310-1313`): already REST, unchanged.
- The inspector plugin's GraphQL batch (`plugins/inspector/skills/inspect/scripts/evidence.py:1194-1301`): a
  separate plugin with its own per-PR fallback.
- The agent guard that refuses factory agents' `gh pr` / `gh api` (unchanged; the hooks and the main Claude
  make these calls, not agents).
- Changing the queue file, the `Issue` type's fields, the issue file format, or the comment texts.

## Design

### Repository addressing

Every endpoint is written with gh's own placeholders, `repos/{owner}/{repo}/...`, which `gh api` fills from the
checkout's git remote (the same repository `gh issue ...` resolved before). The hooks pass the literal string
`{owner}/{repo}` in argv; there is no shell, so nothing expands it but gh. The issue number in a path is
always `String(n)` of an integer (`startIssue` already gets a number); label names in a path are the module
constants, passed through `encodeURIComponent` (`factory:needs-info` -> `factory%3Aneeds-info`).

### The calls (register.tsx)

All through the existing `gh($, args, cwd)` helper (argv array, 60 s timeout). Text values are sent with
`-f` (`--raw-field`, never `-F`), so a body that starts with `@` is never read as a file and nothing is
type-coerced.

| Operation | Today | REST argv (after `gh`) |
|---|---|---|
| List the queue (`queueNow`, `runQueue`) | `issue list --label factory --state open --limit 100 --json number,title` | `api --paginate repos/{owner}/{repo}/issues?labels=factory&state=open&per_page=100` |
| View an issue (`fetchIssue`) | `issue view <n> --json ...` | `api repos/{owner}/{repo}/issues/<n>` then `api --paginate repos/{owner}/{repo}/issues/<n>/comments?per_page=100` |
| Comment (`ghComment`) | `issue comment <n> --body <b>` | `api -X POST repos/{owner}/{repo}/issues/<n>/comments -f body=<b>` |
| Create a label (`ghLabel`, add) | `label create <l> --force --color <c>` | `api -X POST repos/{owner}/{repo}/labels -f name=<l> -f color=<c>` (a 422 "already exists" is ignored, as the result is today) |
| Add a label | `issue edit <n> --add-label <l>` | `api -X POST repos/{owner}/{repo}/issues/<n>/labels -f labels[]=<l>` |
| Remove a label | `issue edit <n> --remove-label <l>` | `api -X DELETE repos/{owner}/{repo}/issues/<n>/labels/<encodeURIComponent(l)>` (a 404, label not on it, is ignored) |

The list's query string uses `LABEL`; build it from the constant, not a literal.

`fetchIssue` makes the two calls in order; if either exits non-zero it returns
`Couldn't read issue #<n> with gh: <stderr tail>` as today. It never builds an `Issue` from the issue object
alone when the comments call failed (fail closed: a run on partial comments could miss the author's answer, or
resume on the wrong state).

### The parsers (issues.ts)

Replace `parseIssue` and `parseIssueList` (their GraphQL-`--json` shapes are no longer produced) with:

```ts
// `gh api repos/{owner}/{repo}/issues/<n>` and its `/comments` (paged). A pull request: 'pull-request'.
// Not that shape: null.
export function parseRestIssue(issueJson: string, commentsJson: string): Issue | 'pull-request' | null
// `gh api --paginate repos/{owner}/{repo}/issues?labels=factory&state=open`: open issues labeled `factory`,
// pull requests left out, oldest first.
export function parseRestIssueList(json: string): { number: number; title: string }[]
// gh --paginate output: one JSON array, or several pages back to back (`[...][...]`), as one flat list.
export function parsePages(json: string): unknown[] | null
```

Mapping for `parseRestIssue` (REST field -> `Issue` field):

- `number` (must be a number) and `title` (must be a string), else `null`.
- `pull_request` present and non-null -> `'pull-request'`.
- `body`: string, or `''` when `null`/missing.
- `state`: `String(state).toUpperCase()` (`open` -> `OPEN`), so `refusal` is unchanged.
- `author`: `user.login` as a string, `''` when `user` is null (a deleted account).
- `labels`: each entry's `name` when it is an object, the entry itself when it is a string.
- `url`: `html_url`.
- `comments`: **from `commentsJson` only**, through `parsePages`; each `{ author: user.login ?? '', body:
  String(body ?? ''), createdAt: String(created_at ?? '') }`. The issue object's own `comments` field is a
  count (a number) in REST and is never read. `commentsJson` not parseable as pages -> `null` (the whole
  issue), not an issue with no comments.

`parseRestIssueList`: `parsePages`; keep entries with a numeric `number`, no `pull_request`, `state` equal
to `open` (case-insensitive) and a label named `LABEL`; map to `{ number, title: String(title ?? '') }`;
sort by number ascending. Not parseable: `[]` (as today, and the call's exit code still reports a gh failure).

`parsePages`: `JSON.parse` the text; an array -> it; otherwise split back-to-back top-level arrays (`][`
between pages, with optional whitespace) and concatenate them; an array of arrays (`--slurp` form) is
flattened one level. Anything else -> `null`. It must not use string splitting that a `][` inside a JSON
string value (an issue title or comment body) could break: parse incrementally (for example, find each
top-level array's end by a bracket/string-aware scan) or try `JSON.parse('[' + text.replace(...) + ']')`
only as a whole-document parse that fails safely.

`refusal` and `trustedComments` keep their behaviour. One tightening at the trust boundary:
`trustedComments` never trusts a comment whose author is `''`, even when the issue's author is also `''`
(two deleted accounts must not match each other). The existing `parseIssue`'s callers move to
`parseRestIssue`; a `'pull-request'` result makes `fetchIssue` return
`#<n> is a pull request, not an issue: the factory builds open issues only.`

### The PR step (flow.ts)

`prCommands(run)` becomes:

1. `git -C <worktree> push -u origin <branch>` (unchanged).
2. `gh api -X POST repos/{owner}/{repo}/pulls -f head=<branch> -f base=<base> -f title=<JSON-quoted title> -F body=@<the body below, saved to a file> --jq .html_url`.
   With no `prBase(run)`, `base=` is the repository's default branch, named in the command as
   `-f base=<the default branch: gh api repos/{owner}/{repo} --jq .default_branch>` (REST requires `base`).
   `-F` is used here only for `body=@file`, which reads the file Claude or the person wrote.

`prPrompt`:

- The "Push branch ... and open a pull request" line adds: open it through GitHub's REST API (the `gh api`
  command below) or the session's own GitHub tools, not `gh pr create`, which uses GraphQL that cloud
  sessions refuse.
- The autoMerge line says: merge it with
  `gh api -X PUT repos/{owner}/{repo}/pulls/<number>/merge -f merge_method=merge`, with the same
  refuse-don't-force wording. It no longer contains `gh pr merge`.
- The no-push (handed) branch lists the new `prCommands`.

`register.tsx` has a second copy of `prBase` (`prBaseOf`, line 1256); it is unchanged and must agree with
`prBase` (both strip `origin/` / `upstream/`).

### Failure modes

- gh missing or not logged in: `gh()` returns exit 1; the list and view paths return their existing
  "Couldn't ... with gh" messages; comment failures are toasted; label failures are ignored (as today).
- The remote isn't GitHub, so gh can't fill `{owner}/{repo}`: gh exits non-zero; same messages.
- A page of the list or comments fails mid-`--paginate`: gh exits non-zero; treated as a failure, not a
  partial list.
- REST returns a PR for an issue number: refused by number, skipped in the list.
- Unexpected JSON: `parseRestIssue` -> `null` -> `gh answered for #<n> in a shape the factory can't read.`
- Issue body or comment text containing instructions: unchanged handling; it only reaches
  `.factory/issues/<n>.md` as quoted data via `issueFile`.

## Acceptance criteria

1. `queueNow` and `runQueue` run `gh api --paginate repos/{owner}/{repo}/issues?labels=factory&state=open&per_page=100`
   and no `gh issue list`; a test asserts the exact argv in `w.ran`.
2. `parseRestIssueList` on a REST page holding an open `factory` issue, a closed one, one without the label and
   a pull request (`pull_request: {...}`) returns only the first; with two pages back to back (`[..][..]`) it
   returns the issues of both, sorted by number; a title containing `][` does not break parsing.
3. `fetchIssue` runs `gh api repos/{owner}/{repo}/issues/<n>` and
   `gh api --paginate repos/{owner}/{repo}/issues/<n>/comments?per_page=100`, and no `gh issue view`.
4. `parseRestIssue` maps `user.login`, `html_url`, `state: "open"` -> `OPEN`, `body: null` -> `''`, label
   objects and strings, and takes comments only from the comments JSON (an issue whose own `comments` is the
   number `3` and whose comments JSON is `[]` has no comments). A non-array comments JSON gives `null`.
5. With a comment from `mallory`, one from the issue's author and one from the operator `op`, the issue file
   written by `/factory run <n>` contains the author's and the operator's and not mallory's; a comment
   starting with `<!-- factory -->` by the author is left out; a comment with author `''` on an issue whose
   author is `''` is left out.
6. `/factory run <n>` on a closed issue, an issue without the `factory` label, and a pull request number each
   refuse to start (no agent spawned), with the closed / no-label messages unchanged and the pull-request
   message from the Design.
7. If the comments call exits non-zero, `/factory run <n>` returns `Couldn't read issue #<n> with gh: ...` and
   writes no issue file.
8. Comments are posted with `gh api -X POST repos/{owner}/{repo}/issues/<n>/comments -f body=<!-- factory -->...`
   (the existing accept, ask and reject tests rewritten to this form); no `gh issue comment` and no `-F` in it.
9. Parking on NEEDS-INFO runs `gh api -X POST repos/{owner}/{repo}/labels -f name=factory:needs-info -f color=FBCA04`
   and `gh api -X POST repos/{owner}/{repo}/issues/<n>/labels -f labels[]=factory:needs-info`; resuming runs
   `gh api -X DELETE repos/{owner}/{repo}/issues/<n>/labels/factory%3Aneeds-info`. No `gh issue edit` or
   `gh label create` is run anywhere (grep of `register.tsx` finds no `'issue', '` or `'label', 'create'` argv).
10. The approved PR prompt (push allowed) names `gh api -X POST repos/{owner}/{repo}/pulls` with `head`, the
    base and the title, and says not to use `gh pr create`; with no base the command names the default branch
    lookup; the no-push prompt lists the same command for the person.
11. With autoMerge on and the approver's approval, the prompt contains
    `gh api -X PUT repos/{owner}/{repo}/pulls/<number>/merge -f merge_method=merge` and not `gh pr merge`;
    without autoMerge it contains neither (tests at `factory.test.tsx:2944-2981` updated).
12. README.md (lines 340, 365) and the `autoMerge` description in `plugins/factory/.claude-plugin/plugin.json`
    no longer name `gh pr create` / `gh pr merge` as what the factory hands out.
13. `claude plugin test plugins/factory` passes, and `claude plugin validate plugins/factory` passes.

## Open questions

- Whether `gh api` fills `{owner}/{repo}` from a cloud session's remote without a GraphQL call. Assumed yes:
  the refusal message itself recommends `gh api repos/{owner}/{repo}/...`, and `gh api` resolves its base
  repository from the git remotes. If it does not, resolving the slug from `git remote get-url origin` (as
  `evidence.py:1418-1423` does) is the fallback; not built now.
- `-f labels[]=<l>` needs gh's array-field syntax (gh 2.x). Assumed available in the sessions the factory runs
  in; the label add result is ignored today, so an old gh degrades to a missing label, not a broken run.

## Code map

Files the change touches:

- `plugins/factory/hooks/issues.ts` (148 lines). Changes: new REST parsers, `trustedComments` tightening.
  - `:6-10` constants `LABEL = 'factory'`, `NEEDS_INFO_LABEL = 'factory:needs-info'`, `NEEDS_HUMAN_LABEL = 'factory:needs-human'`, `MARKER = '<!-- factory -->'`.
  - `:12-13` types (unchanged):
    `type IssueComment = { author: string; body: string; createdAt: string }`
    `type Issue = { number: number; title: string; body: string; state: string; author: string; labels: string[]; comments: IssueComment[]; url: string }`
  - `:37-61` `parseIssue` (GraphQL `--json` shape): replaced by `parseRestIssue`.
  - `:63-75` `parseIssueList`: replaced by `parseRestIssueList` (+ `parsePages`).
  - `:77-82` `refusal`: unchanged, relies on `state` upper-cased and `labels` as names.
  - `:84-87` `trustedComments`: the trust filter; add the empty-author rule.
  - `:89-106` `issueFile`, `:113-116` `answeredSince`: consumers, unchanged.
- `plugins/factory/hooks/register.tsx` (large; read by range). Changes: the gh argv and `fetchIssue`.
  - `:85-86` imports from `./issues` (swap `parseIssue`, `parseIssueList` for the REST ones).
  - `:1286-1288` `gh()` helper: `$.process.run(['gh', ...args], { cwd, timeoutMs: 60_000 })`, errors as exit 1.
  - `:1301-1304` `ghComment`; `:1305-1308` `ghLabel` (colors FBCA04 needs-info, D93F0B otherwise).
  - `:1310-1313` `operatorOf` (already REST, unchanged).
  - `:1314-1318` `fetchIssue`: two REST calls, PR refusal.
  - `:1322-1343` `startIssue` (caller; unchanged logic). `:1345-1352` `queueNow`, `:1356-1387` `runQueue`: list argv.
  - `:1256` `prBaseOf`: copy of `flow.ts` `prBase`, unchanged.
  - `:1658-1705` `doctorText`: out of scope.
- `plugins/factory/hooks/flow.ts`. Changes: PR commands and prompt text.
  - `:553` `prBase`; `:556-559` `prCommands` (used in the handed branch and in the "can't open it" line);
    `:561-587` `prPrompt` (line 574 open-PR line, 576 autoMerge line, 577 fallback commands).
- `plugins/factory/tests/factory.test.tsx`. Changes: mock and tests.
  - `:9` imports from `../hooks/issues`.
  - `:156-163` the engine's gh mock (`issues` option): answers `gh issue view/list` and `gh api user --jq .login`,
    all other gh OK. Move to REST: answer `gh api repos/{owner}/{repo}/issues/<n>`, `.../issues/<n>/comments`
    and the list endpoint from REST-shaped fixtures; keep `gh api user --jq .login` -> `op` matched before them.
    `cmd` there is `e.argv.join(' ')`.
  - `:2944-2981` autoMerge / no-merge PR prompt tests (`/gh pr merge/`).
  - `:2986-2989` `issue()` fixture (GraphQL shape: `author.login`, `labels[{name}]`, `comments[]`, `url`,
    `state: 'OPEN'`): becomes REST shape (`user.login`, `html_url`, `state: 'open'`, comments served separately).
  - `:2991-3066` issue-queue tests (comment and label argv assertions at 3014, 3039, 3040, 3051, 3059).
  - `:3068-3119` concurrency tests that use `issues` (should pass unchanged once the mock is REST).
- `README.md:340` (`gh pr create` commands for a no-push feature) and `:365` (`autoMerge` ... `gh pr merge`):
  text names the old commands.
- `plugins/factory/.claude-plugin/plugin.json:80`: `autoMerge` option description names `gh pr merge`.

Copies of the logic:

- `prBase` (`flow.ts:553`) and `prBaseOf` (`register.tsx:1256`): same logic, both in scope only to keep them equal (no change needed).
- GraphQL gh use in `plugins/inspector/skills/inspect/scripts/evidence.py:1194-1301` and its tests: out of scope (other plugin, has its own fallback).
- `plugins/factory/docs/findings/2026-10-29-factory-run-review.md:50` mentions `gh pr create`: a dated record, out of scope.
- README `:384` mentions agents' `gh pr` being refused (the guard): accurate, out of scope.

Commands:

- `claude plugin test plugins/factory` (the kit tests, including `factory.test.tsx`).
- `claude plugin validate plugins/factory`.
- `node --experimental-strip-types --test plugins/factory/tests/history.real-git.mjs` (unaffected; CI runs it).
