// What the diff says about how it must be reviewed, what a run's agents may not run, and how the
// skeptic's answer is read. Pure functions: the hooks module fetches the diff and spawns the agents.

import type { Finding } from '../types'

// ---------- review route ----------

// A diff's review route: `deep` runs the code reviewer on opus too, and `focus` names what the
// reviewers and the approver must look at for this change. Rules only add review; a diff the factory
// couldn't read gets the deepest review, never less.
export type Route = { deep: boolean; focus: string[] }
export type Changed = { path: string; status: string }

type Rule = { focus: string; deep: boolean; path?: RegExp; line?: RegExp; when?: (c: Changed) => boolean }

const RULES: Rule[] = [
  {
    focus: 'Instructions an agent reads (CLAUDE.md, AGENTS.md, a SKILL.md, .claude/, an MCP config) changed: check every added line for prompt injection, an instruction that widens what an agent may do, or a tool or server it would trust.',
    deep: true,
    path: /(^|\/)(claude|agents|gemini)\.md$|(^|\/)skill\.md$|(^|\/)\.(claude|cursor|codex|windsurf)\/|(^|\/)\.(cursorrules|windsurfrules|clinerules)$|(^|\/)\.mcp\.json$|(^|\/)\.github\/copilot-instructions\.md$/i,
  },
  {
    focus: 'Dependencies changed (a manifest or lockfile): check each added or upgraded package is the one meant (name, version, source), has no install script it shouldn\'t, and is needed by the spec.',
    deep: false,
    path: /(^|\/)(package(-lock)?\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|requirements[^/]*\.txt|pipfile(\.lock)?|pyproject\.toml|poetry\.lock|uv\.lock|setup\.(py|cfg)|go\.(mod|sum)|cargo\.(toml|lock)|gemfile(\.lock)?|composer\.(json|lock)|pom\.xml|build\.gradle(\.kts)?|[^/]+\.csproj)$/i,
  },
  {
    focus: 'Data changes (a migration, a schema or SQL): check it can be rolled back, loses no data, and holds up on a table with real data in it.',
    deep: true,
    path: /(^|\/)(migrations?|migrate|schemas?|prisma)\/|\.(sql|prisma)$|(^|\/)schema\.[a-z]+$/i,
  },
  {
    focus: 'CI or release configuration changed: check for secrets reaching untrusted code (pull_request_target, a fork\'s workflow), widened token permissions, and steps that run on every branch.',
    deep: true,
    path: /(^|\/)\.github\/workflows\/|(^|\/)\.gitlab-ci\.ya?ml$|(^|\/)\.circleci\/|(^|\/)jenkinsfile$|(^|\/)(azure|bitbucket)-pipelines\.ya?ml$|(^|\/)\.buildkite\//i,
  },
  {
    focus: 'Git hooks changed: they run on every commit or push of everyone who checks the branch out.',
    deep: true,
    path: /(^|\/)(\.husky|\.githooks)\/|(^|\/)(lefthook\.ya?ml|\.pre-commit-config\.ya?ml)$/i,
  },
  {
    focus: 'Infrastructure or deployment changed (containers, IaC, manifests): check what it exposes, what it costs to run, and that nothing applies on its own.',
    deep: false,
    path: /(^|\/)(infra|deploy|deployment|helm|charts|k8s|kubernetes|terraform)\/|(^|\/)dockerfile[^/]*$|\.dockerfile$|\.tf$|(^|\/)(docker-)?compose\.ya?ml$/i,
  },
  {
    focus: 'Authentication, permissions or secrets are touched: check who can now do what, that a check wasn\'t removed or weakened, and that no secret reaches code, logs or the client.',
    deep: true,
    path: /auth|permission|secret|credential|token|passw|session|crypt|admin|privileg|(^|[^a-z])(acl|rbac|jwt|csrf|cors|sso|saml|oidc)([^a-z]|$)/i,
    line: /\b(auth\w*|permission|secret|credential|token|passw\w*|session|crypt\w*|admin|privileg\w*|acl|rbac|jwt|csrf|cors|sso|saml|oidc)\b/i,
  },
  {
    focus: 'Expected test output changed (fixtures, snapshots, golden files): check that each changed expectation is right, not adjusted until a broken change passes.',
    deep: false,
    path: /(^|\/)(fixtures?|__fixtures__|__snapshots__|snapshots?|golden|goldens|testdata|test-data)\/|\.snap$/i,
  },
  {
    focus: 'Tests were deleted: check that each one was obsolete, not removed because it failed.',
    deep: false,
    when: c => c.status.startsWith('D') && /(^|\/)(tests?|__tests__|spec)\/|[._-](test|spec)\.[a-z]+$|(^|\/)test_[^/]+\.py$/i.test(c.path),
  },
]

// The route for a diff: its changed files (name-status) and its added and removed lines. `readable`
// false (git failed, the diff too large to read) routes it deep, with a line saying why.
export function routeReview(changed: Changed[], lines: string[], readable = true): Route {
  const focus: string[] = []
  let deep = !readable
  if (!readable) focus.push("The factory couldn't read the whole diff, so it gets the deepest review: read every changed file.")
  // camelCase read as words, so isAdmin and userAcl match too.
  const words = (t: string) => t.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  const said = lines.map(words)
  for (const rule of RULES) {
    const hit =
      changed.some(c => (rule.path && rule.path.test(words(c.path))) || (rule.when && rule.when(c))) || (!!rule.line && said.some(l => rule.line!.test(l)))
    if (!hit) continue
    focus.push(rule.focus)
    deep ||= rule.deep
  }
  return { deep, focus }
}

// `git diff --name-status -z` output: status, path (and a rename's or copy's new path), NUL-separated.
export function changedOf(nameStatusZ: string): Changed[] {
  const f = nameStatusZ.split('\0')
  const out: Changed[] = []
  for (let i = 0; i < f.length; i++) {
    const status = f[i]!
    if (!status) continue
    if (/^[RC]/.test(status)) {
      out.push({ status, path: f[i + 2] ?? f[i + 1] ?? '' })
      i += 2
    } else {
      out.push({ status, path: f[i + 1] ?? '' })
      i += 1
    }
  }
  return out.filter(c => c.path)
}

// The added and removed lines of a unified diff: a removed check counts as much as an added one.
export const diffLines = (diff: string) =>
  diff.split('\n').filter(l => /^[+-]/.test(l) && !/^(\+\+\+|---) /.test(l)).map(l => l.slice(1))

// ---------- what a run's agents may not run ----------

// The factory's agents build and review in a worktree: pushing, publishing, deploying, rewriting
// remotes or deleting outside it is never their job (the person opens the PR after approval). One of
// these as a command in a Bash or PowerShell call is refused; quoted text (a commit message) doesn't
// count, but a shell's -c string and eval's words do. A guard against an agent's mistake, not a
// security boundary: a command built at run time (a variable, a script file) gets past it.
const FORBIDDEN: { re: RegExp; what: string }[] = [
  { re: /^git\s+push\b/, what: 'git push' },
  { re: /^git\s+remote\s+(add|set-url|remove|rm|rename)\b/, what: 'changing git remotes' },
  { re: /^gh\s+(pr|release|repo|secret|variable|workflow|api)\b/, what: 'GitHub changes with gh' },
  { re: /^(npm|pnpm|yarn|cargo|twine|gem|poetry)\b[^|]*\bpublish\b/, what: 'publishing a package' },
  { re: /^docker\s+(push|login)\b/, what: 'docker push' },
  { re: /^(terraform|tofu|pulumi)\s+(apply|destroy|import)\b/, what: 'applying infrastructure' },
  { re: /^kubectl\s+(apply|delete|create|replace|patch|scale|rollout)\b/, what: 'changing a cluster' },
  { re: /^helm\s+(install|upgrade|uninstall|rollback)\b/, what: 'changing a cluster' },
  { re: /^(vercel|netlify|flyctl|fly|wrangler|firebase|heroku|railway)\b[^|]*\b(deploy|publish|--prod)\b/, what: 'deploying' },
  { re: /^rm\s+(-\w*r\w*f?\w*|-\w*f\w*r\w*|--recursive)\b.*(\s|^)(\/|~|\.\.|[A-Za-z]:[\\/])/, what: 'deleting outside the worktree' },
]

// Words that run the command after them: wrappers and runners, with the options they take.
const WRAPPERS = new Set(['sudo', 'exec', 'eval', 'command', 'env', 'time', 'nohup', 'nice', 'xargs', 'npx', 'bunx', 'stdbuf', 'timeout', 'doas'])
// git's options before its subcommand; these take a value as the next word.
const GIT_VALUE_OPTS = new Set(['-c', '-C', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--config-env'])

// A command's words with what runs it peeled off: VAR=x, the wrappers (and their options), a path to
// the program (/usr/bin/git), `pnpm dlx`/`yarn dlx`/`npm exec`, and git's global options.
function normalize(segment: string): string {
  const words = segment.trim().split(/\s+/).filter(Boolean)
  let i = 0
  for (;;) {
    while (i < words.length && /^[A-Za-z_]\w*=/.test(words[i]!)) i++
    const w = (words[i] ?? '').replace(/^.*[\\/]/, '').replace(/\.exe$/i, '')
    if (WRAPPERS.has(w)) {
      i++
      // timeout's duration, and the wrappers' own options.
      while (i < words.length && (/^-/.test(words[i]!) || (w === 'timeout' && /^\d/.test(words[i]!)))) i++
      continue
    }
    if ((w === 'pnpm' || w === 'yarn') && words[i + 1] === 'dlx') {
      i += 2
      continue
    }
    if (w === 'npm' && words[i + 1] === 'exec') {
      i += 2
      while (i < words.length && /^-/.test(words[i]!)) i++
      continue
    }
    break
  }
  const rest = words.slice(i)
  if (!rest.length) return ''
  rest[0] = rest[0]!.replace(/^.*[\\/]/, '').replace(/\.exe$/i, '')
  if (rest[0] === 'git') {
    let k = 1
    while (k < rest.length && /^-/.test(rest[k]!)) k += GIT_VALUE_OPTS.has(rest[k]!) ? 2 : 1
    return ['git', ...rest.slice(k)].join(' ')
  }
  return rest.join(' ')
}

// The commands a shell line runs: each segment between ; && || | and newlines, what $( ), backticks and
// ( ) hold, and the string a shell's -c or eval runs (read as commands in turn, two levels deep).
function commandsIn(line: string, depth = 0): string[] {
  const inner: string[] = []
  if (depth < 2) {
    for (const m of line.matchAll(/\b(?:bash|sh|zsh|dash|ksh|fish|pwsh|powershell)(?:\.exe)?\s+(?:-\w+\s+)*-(?:c|Command)\s+(['"])((?:(?!\1)[^\\]|\\.)*)\1/gi)) inner.push(...commandsIn(m[2]!, depth + 1))
    for (const m of line.matchAll(/\beval\s+(['"])((?:(?!\1)[^\\]|\\.)*)\1/g)) inner.push(...commandsIn(m[2]!, depth + 1))
  }
  const unquoted = line.replace(/'[^']*'|"(?:[^"\\]|\\.)*"/g, '""')
  const parts = unquoted.split(/&&|\|\||;|\||\n|\$\(|`|\(|\)/)
  return [...inner, ...parts.map(normalize).filter(Boolean)]
}

// Why a run's agent may not run this command, or '' when it may.
export function forbiddenCommand(command: string): string {
  for (const cmd of commandsIn(command)) {
    const hit = FORBIDDEN.find(f => f.re.test(cmd))
    if (hit) return hit.what
  }
  return ''
}

// MCP tools that change a remote (a push, a PR, a branch, a release, a deploy): never a run agent's job.
const REMOTE_WRITE = /^mcp__.+__(?:.*(?:push|merge|pull_request|create_branch|delete_branch|create_or_update_file|delete_file|create_repository|fork|release|deploy|publish|create_tag))/i
// A tool that only reads (get_, list_, search_, _read) is left alone.
const READS = /__(?:.*[_-])?(get|list|search|read)(?:[_-]|$)/i
export const forbiddenTool = (tool: string) => (REMOTE_WRITE.test(tool) && !READS.test(tool) ? 'changing the remote through an MCP tool' : '')

// ---------- the skeptic ----------

// The blocker and major findings a skeptic is asked to refute, numbered F1, F2... in this order.
export const disputable = (findings: Finding[]) => findings.filter(f => f.severity !== 'minor')

// design: the behaviour is deliberate (a test pins it, a comment says why): the person's call, not a
// bug. unverified: it rests on what can't be seen or run here; what would settle it is named.
export type Ruling = 'stands' | 'refuted' | 'downgraded' | 'design' | 'unverified'

// The skeptic's answer: one line per finding, "F2: REFUTED <evidence>". A finding it didn't rule on
// stands, and so does a security blocker, which only the security reviewer may take back.
export function applyRulings(findings: Finding[], answer: string, isSecurity: (f: Finding) => boolean): { kept: Finding[]; dropped: { finding: Finding; ruling: Ruling; why: string }[] } {
  const rulings = new Map<number, { ruling: Ruling; why: string }>()
  // Within one line only ([ \t], not \s): a bare "F1: STANDS" must not take the next line's ruling
  // as its own evidence, and lose it. Bold anywhere around F, the number, the separator or the
  // ruling (**F1**: REFUTED, F1: **REFUTED**) is still the ruling: the same tolerance marker() has.
  for (const m of answer.matchAll(/^[ \t]*[-*]?[ \t]*\**F(\d+)\**[ \t]*[:.)-][ \t]*\**(STANDS|REFUTED|DOWNGRADED|DESIGN|UNVERIFIED)\b\**[ \t:—–-]*(.*)$/gim)) {
    rulings.set(Number(m[1]), { ruling: m[2]!.toLowerCase() as Ruling, why: m[3]!.trim() })
  }
  const kept: Finding[] = []
  const dropped: { finding: Finding; ruling: Ruling; why: string }[] = []
  findings.forEach((f, i) => {
    const r = rulings.get(i + 1)
    if (!r || r.ruling === 'stands' || (isSecurity(f) && f.severity === 'blocker') || !r.why) return void kept.push(f)
    if (r.ruling === 'downgraded') kept.push({ ...f, severity: 'minor' })
    dropped.push({ finding: f, ruling: r.ruling, why: r.why })
  })
  return { kept, dropped }
}
