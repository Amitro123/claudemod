// The factory's pure parts: what each role is told, how its answer is read, which checks run, and
// how a run starts. The hooks module only spawns, runs and draws.

import type { Check, Extra, Finding, Phase, Review, Reviewer, Role, Run, Severity, Size, SpecTask, StepState } from '../types'
import { FACTORY_SOURCE } from './texts'

export const REVIEWERS: Reviewer[] = ['security', 'code']

// Each role as an agent type `factory:<name>`, with the model it runs on by default: sonnet does
// the writing and building; opus is kept where a miss costs most, the security review and the
// approval. A large feature moves the builder up to opus too (modelsFor).
export const ROLES: Record<Role, { name: string; model: string; label: string; tools?: string[] }> = {
  spec: { name: 'spec-writer', model: 'sonnet', label: 'spec-writer', tools: ['Read', 'Grep', 'Glob', 'Write', 'Edit', 'Bash'] },
  builder: { name: 'builder', model: 'sonnet', label: 'builder' },
  security: { name: 'security-reviewer', model: 'opus', label: 'security', tools: ['Read', 'Grep', 'Glob', 'Bash'] },
  code: { name: 'code-reviewer', model: 'sonnet', label: 'code', tools: ['Read', 'Grep', 'Glob', 'Bash'] },
  approver: { name: 'approver', model: 'opus', label: 'approver', tools: ['Read', 'Grep', 'Glob'] },
  skeptic: { name: 'skeptic', model: 'sonnet', label: 'skeptic', tools: ['Read', 'Grep', 'Glob', 'Bash'] },
  extra: { name: 'reviewer', model: 'sonnet', label: 'reviewer', tools: ['Read', 'Grep', 'Glob', 'Bash'] },
}

// ---------- extra reviewers ----------

// What the main Claude can add for a run that needs it, beside security and code (which always run).
// Each is the factory's generic reviewer with this lens; an agent type of the session can run one instead.
export const LENSES: Record<string, string> = {
  frontend: 'the user-facing side: every state a screen can be in (loading, empty, error, long text), keyboard and screen-reader access (WCAG 2.2 AA), responsive layout, and copy that matches what the code does',
  finops: 'what the change costs to run: new paid resources or calls, per-request costs, scaling and instance settings, retention, egress, and limits that keep a mistake from becoming a bill',
  deploy: 'whether it can ship safely: the order of migrations and code, config and secrets it now needs in each environment, a way to roll back, a flag for a risky path, and the logs or metrics to see it working',
  performance: 'how it behaves under load: N+1 queries, missing indexes, unbounded loops or result sets, work done per request that could be done once, memory held too long',
  api: 'its public contract: backward compatibility for existing callers, versioning, error shapes and status codes, validation at the boundary, and documentation of what changed',
  data: 'the data it touches: migrations that are safe on a large table and can be undone, personal data (where it goes, who can read it, how long it stays), and integrity under concurrent writes',
}
export const MAX_EXTRAS = 3
export const CORE_REVIEWERS = new Set(['security', 'code'])
export const isExtra = (role: Reviewer) => !CORE_REVIEWERS.has(role)

// The reviewers the main Claude asked for, as the factory runs them: a lens by its name, or one of its
// own with a name, what it looks at and, optionally, the agent type to run. Unknown or empty ones are
// left out, and so are any past the limit: a run never grows past three extra reviewers.
export function extrasFrom(raw: unknown): { extras: Extra[]; ignored: string[] } {
  const extras: Extra[] = []
  const ignored: string[] = []
  for (const item of Array.isArray(raw) ? raw : []) {
    const o = (typeof item === 'string' ? { name: item } : item ?? {}) as { name?: unknown; lens?: unknown; focus?: unknown; agent?: unknown }
    const name = String(o.name ?? o.lens ?? '').trim().toLowerCase().replace(/[^a-z0-9-]+/g, '-').slice(0, 24)
    const focus = String(o.focus ?? '').trim() || LENSES[name] || ''
    const agent = String(o.agent ?? '').trim()
    if (!name || !focus || CORE_REVIEWERS.has(name) || extras.some(e => e.name === name)) {
      if (name) ignored.push(name)
      continue
    }
    if (extras.length >= MAX_EXTRAS) {
      ignored.push(name)
      continue
    }
    extras.push({ name, focus: focus.slice(0, 400), ...(agent ? { agent } : {}) })
  }
  return { extras, ignored }
}

export const reviewerLabel = (role: Reviewer) => (CORE_REVIEWERS.has(role) ? ROLES[role as Role].label : role)
// An extra reviewer runs on sonnet, or on its own agent's model.
export const reviewerModel = (run: Pick<Run, 'models' | 'extras'>, role: Reviewer) =>
  CORE_REVIEWERS.has(role) ? modelOf(run, role as Role) : run.extras?.find(e => e.name === role)?.agent ? 'its own' : modelOf(run, 'extra')

// The roles' standing instructions, short defaults; a project's own skills can say more.
export const ROLE_PROMPTS: Record<Role, string> = {
  spec: `You are the spec-writer of a software factory. You turn a feature request into a spec a builder can implement and reviewers can check against: a short PRD (the problem, who it's for, what's out of scope), a technical spec (the design, interfaces, data, failure modes) and numbered acceptance criteria, each testable. Read the code you need first; don't write any implementation.`,
  builder: `You are the builder of a software factory. You implement exactly what the spec asks, in the repository you are started in, with tests for each acceptance criterion. Keep the change focused; don't refactor beyond it. Commit your work to the current branch when you are done.`,
  security: `You are the security reviewer of a software factory. Review the change against the spec for: injection and unsafe input handling, authentication and authorization, secrets in code or logs, unsafe defaults, dependency risk, and data exposure. Report only real, specific problems.`,
  code: `You are the code reviewer of a software factory. Review the change against the spec for: correctness against each acceptance criterion, missing or weak tests, error handling, clarity, layering and design, and performance traps. Report only real, specific problems.`,
  skeptic: `You are the skeptic of a software factory. Reviewers found problems in a change; before the builder is sent to fix them, you try to refute each one with evidence: the code at file:line, a definition, or a command's output. You change no file. A finding you can't refute stands: never refute one on opinion.`,
  extra: `You are an extra reviewer of a software factory, added for this change. You review it through the one lens your job names, against the spec. Report only real, specific problems.`,
  approver: `You are the approver of a software factory. You decide whether a change that went through review can go to a pull request. You don't review the code again: you weigh the spec, the check results and the reviewers' verdicts and findings.`,
}

// ---------- reading the agents' answers ----------

// The spec-writer ends with:  TASKS:  then lines  "1. [high] Title (needs 2, 3)".
export function parseTasks(answer: string): SpecTask[] {
  const at = answer.lastIndexOf('TASKS:')
  if (at < 0) return []
  const out: SpecTask[] = []
  for (const raw of answer.slice(at + 6).split('\n')) {
    const m = /^\s*\d+[.)]\s*\[(high|medium|low)\]\s*(.+?)\s*(?:\(needs ([\d,\s]+)\))?\s*$/i.exec(raw)
    if (!m) continue
    out.push({ title: m[2]!.trim(), priority: m[1]!.toLowerCase() as SpecTask['priority'], dependsOn: (m[3] ?? '').split(/[,\s]+/).filter(Boolean).map(Number) })
  }
  return out
}

// The spec-writer's size line:  SIZE: small | medium | large.  None (or another word): null.
export function parseSize(answer: string): Size | null {
  const m = /^\s*SIZE:\s*(small|medium|large)\b/im.exec(answer)
  return m ? (m[1]!.toLowerCase() as Size) : null
}

// The model each role runs on for a feature of this size. 'auto' moves the builder up to opus for a
// large one; 'fixed' keeps the defaults whatever the size.
export function modelsFor(size: Size | null, mode: 'auto' | 'fixed'): Record<Role, string> {
  const out = Object.fromEntries((Object.keys(ROLES) as Role[]).map(r => [r, ROLES[r].model])) as Record<Role, string>
  if (mode === 'auto' && size === 'large') out.builder = 'opus'
  return out
}

// The factory's own skill for a role, shipped in the plugin (skills/<name>/SKILL.md): its method.
export const builtinSkill = (role: Role) => `factory:${ROLES[role].name}`

// The skills option: which skills a role loads before its job, in place of the factory's own, as
// "role=skill,skill; role=skill" (spec, builder, security, code, approver); "role=none" loads none.
// A skill can be a plugin's, plugin:name. Unknown roles and empty names are left out.
export function parseSkills(text: string): Partial<Record<Role, string[]>> {
  const out: Partial<Record<Role, string[]>> = {}
  for (const part of text.split(';')) {
    const at = part.indexOf('=')
    if (at < 0) continue
    const role = part.slice(0, at).trim().toLowerCase() as Role
    if (!(role in ROLES)) continue
    const names = part.slice(at + 1).split(',').map(x => x.trim()).filter(Boolean)
    // none: the role loads no skill, not even the factory's own.
    if (names.length === 1 && names[0]!.toLowerCase() === 'none') out[role] = []
    else if (names.length) out[role] = [...(out[role] ?? []), ...names]
  }
  return out
}

// What a role is told first when it has skills: load them, and follow them for this job.
export const skillsLine = (names: readonly string[]) =>
  `Before anything else, load ${names.length === 1 ? 'this skill' : 'these skills'} with the Skill tool and follow ${names.length === 1 ? 'it' : 'them'} for this job: ${names.map(n => `Skill(${n})`).join(', ')}. If one isn't installed, say so in your answer and go on without it.`

export const modelOf = (run: Pick<Run, 'models'> | null | undefined, role: Role) => run?.models?.[role] ?? ROLES[role].model

// The answer's markers (`KEY: <option>`), from the lines that hold exactly one: a line holding both
// options ("VERDICT: PASS or VERDICT: CHANGES") is the prompt's template echoed, not an answer.
// None found: undefined. Markers that disagree: `safe`, the outcome that can't wave a change through.
function marker(answer: string, key: string, options: string, safe: string): { value?: string; mixed: boolean } {
  const found = new Set<string>()
  for (const line of answer.split('\n')) {
    const all = [...line.matchAll(new RegExp(`${key}:\\s*(${options})`, 'gi'))]
    if (all.length === 1) found.add(all[0]![1]!.toUpperCase())
  }
  if (found.size > 1) return { value: safe, mixed: true }
  return { value: [...found][0], mixed: false }
}

const FINDING = /^\s*[-*]\s*\[(blocker|major|minor)\]\s+(\S+)\s+[—–-]?\s*(.+)$/i
const isNone = (t: string) => /^(none|nothing|n\/a|-)?\.?$/i.test(t.trim())

// The reviewer's own words for what the change must do: its UNDERSTOOD line, the last one.
export function parseUnderstood(answer: string): string | undefined {
  const all = [...answer.matchAll(/^[\s*_>-]*UNDERSTOOD:\**\s*(.+)$/gim)].map(m => m[1]!.trim()).filter(t => t && !isNone(t) && !/^<.*>$/.test(t))
  return all.at(-1)?.slice(0, 400)
}

// What the reviewer says it did not verify: its NOT CHECKED: line and the list under it. None given:
// undefined (an older format, or a reviewer that skipped it); "NOT CHECKED: none": [].
export function parseNotChecked(answer: string): string[] | undefined {
  const lines = answer.split('\n')
  const at = lines.map(l => /^[\s*_>-]*NOT CHECKED:\**\s*(.*)$/i.exec(l)).reduce((n, m, i) => (m ? i : n), -1)
  if (at < 0) return undefined
  const out: string[] = []
  const first = /NOT CHECKED:\**\s*(.*)$/i.exec(lines[at]!)![1]!.trim()
  if (first && !isNone(first)) out.push(first)
  for (const raw of lines.slice(at + 1)) {
    if (!raw.trim()) {
      if (out.length) break
      continue
    }
    const m = /^\s*[-*]\s+(.+)$/.exec(raw)
    if (!m || FINDING.test(raw)) break
    if (!isNone(m[1]!) && !/^<.*>$/.test(m[1]!.trim())) out.push(m[1]!.trim().slice(0, 300))
  }
  return out.slice(0, 12)
}

// A reviewer ends with:  VERDICT: PASS | CHANGES  and  FINDINGS:  "- [major] path:line what and why".
// No verdict, or both, reads as CHANGES, so a confused reviewer can't wave a change through.
export function parseVerdict(answer: string): { state: 'pass' | 'changes'; findings: Finding[]; understood?: string; notChecked?: string[] } {
  const verdict = marker(answer, 'VERDICT', 'PASS|CHANGES', 'CHANGES')
  const findings: Finding[] = []
  // A finding may run over several lines: the indented lines under it (a list of its own included)
  // are part of it, up to a blank line, the next finding or a marker.
  let open: Finding | null = null
  for (const raw of answer.split('\n')) {
    const m = FINDING.exec(raw)
    if (m) {
      open = { severity: m[1]!.toLowerCase() as Severity, where: m[2]!, text: m[3]!.trim() }
      findings.push(open)
    } else if (open && /^\s+\S/.test(raw) && !/^\s*[A-Z][A-Z ]+:/.test(raw)) open.text = `${open.text} ${raw.trim()}`.slice(0, 1200)
    else open = null
  }
  const understood = parseUnderstood(answer)
  const notChecked = parseNotChecked(answer)
  const said = { ...(understood ? { understood } : {}), ...(notChecked ? { notChecked } : {}) }
  if (!verdict.value) return { state: 'changes', findings: [{ severity: 'major', where: '-', text: 'The reviewer gave no VERDICT line.' }, ...findings], ...said }
  if (verdict.mixed) return { state: 'changes', findings: [{ severity: 'major', where: '-', text: 'The reviewer gave both VERDICT: PASS and VERDICT: CHANGES.' }, ...findings], ...said }
  // A PASS that still lists a blocker isn't a pass.
  const state = verdict.value === 'PASS' && !findings.some(f => f.severity === 'blocker') ? 'pass' : 'changes'
  return { state, findings, ...said }
}

// The builder's own test run, from its closing TESTS: line (the last one). Failing: a count of failures
// above zero, or, with no count, a word of failure that isn't "no failures". None given: undefined.
export function parseBuilderTests(answer: string): { text: string; failing: boolean } | undefined {
  const text = [...answer.matchAll(/^[\s*_>-]*TESTS:\**\s*(.+)$/gim)].map(m => m[1]!.trim()).filter(t => !/^<.*>$/.test(t)).at(-1)
  if (!text) return undefined
  const counts = [...text.matchAll(/(\d+)\s*(?:tests?\s+)?(?:failed|failing|failures?|fail)\b/gi)].map(m => Number(m[1]))
  const failing = counts.length ? counts.some(n => n > 0) : /\bfail/i.test(text) && !/\b(no|none|0|zero)\s+(?:tests?\s+)?fail/i.test(text)
  return { text: text.slice(0, 300), failing }
}

// The builder's closing summary, without its TESTS: line (that one is read on its own).
export const summaryOf = (answer: string) => lastLines(answer.split('\n').filter(l => !/^[\s*_>-]*TESTS:/i.test(l)).join('\n'), 2)

// The feature says not to push or not to open the PR: the factory hands the person the commands instead.
export const forbidsPush = (feature: string) =>
  /\b(do\s*n[o']?t|never|without|no)\s+(git\s+)?push(ing)?\b(?!\s*(notification|message|alert))|\b(do\s*n[o']?t|never|without)\s+(open(ing)?|creat(e|ing))\s+(a\s+|the\s+)?(pr|pull\s+request)\b|(אל|לא|בלי)\s+ל?(תדחוף|לדחוף|דחיפה|push)/i.test(feature)

// The approver ends with:  DECISION: APPROVE | ESCALATE  and  REASON: one line. No decision at all is
// null (it decided nothing: the run waits for a Retry); both is an escalation.
export function parseDecision(answer: string): { decision: 'APPROVE' | 'ESCALATE' | null; reason: string } {
  const found = marker(answer, 'DECISION', 'APPROVE|ESCALATE', 'ESCALATE')
  if (!found.value) return { decision: null, reason: 'The approver gave no DECISION line.' }
  if (found.mixed) return { decision: 'ESCALATE', reason: 'The approver gave both DECISION: APPROVE and DECISION: ESCALATE.' }
  const decision = found.value === 'APPROVE' ? 'APPROVE' : 'ESCALATE'
  const reason = [...answer.matchAll(/REASON:\s*(.+)/gi)].at(-1)?.[1]?.trim() ?? (decision === 'ESCALATE' ? 'The approver gave no reason.' : '')
  return { decision, reason }
}

// ---------- the checks ----------


// With no `checks` set: what the project's own files suggest. Detection lives in checks.ts (never throws).
export { detectChecks, detectProjectChecks, specChecks, allowedCommand, splitChecks, NOTHING_RAN } from './checks'
export type { ChecksIO, DetectedChecks } from './checks'

// A fresh worktree has no installed dependencies: with no `setup` set, the lockfile says how to
// install them. Nothing when they're there already (or the project isn't one of these).
export function detectSetup(files: string[]): string[] | null {
  if (!files.includes('package.json') || files.includes('node_modules')) return null
  if (files.includes('pnpm-lock.yaml')) return ['pnpm', 'install', '--frozen-lockfile']
  if (files.includes('yarn.lock')) return ['yarn', 'install', '--frozen-lockfile']
  if (files.includes('package-lock.json')) return ['npm', 'ci']
  return ['npm', 'install']
}

// The last lines of a failing command's output: enough for the builder, short for the pane.
export const tailOf = (text: string, lines = 30) => text.trim().split('\n').slice(-lines).join('\n')

// ---------- what each step is asked ----------

// The feature as typed or handed over, without the wrapper a paste carries in the prompt.
export const cleanFeature = (text: string) =>
  text.replace(/<\/?pasted_content\b[^>]*>/g, ' ').replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '\n').trim()

// A run's name where a line is all there is (the band, a dialog's first line): the feature's first
// sentence, clipped. A feature is often a whole paragraph of instructions.
export function titleOf(feature: string, n = 60): string {
  const line = feature.trim().split('\n')[0]!.trim()
  const sentence = /^(.+?[.!?])(\s|$)/.exec(line)?.[1] ?? line
  return sentence.length > n ? `${sentence.slice(0, n - 1).trimEnd()}…` : sentence
}

// A branch and folder name from the feature: its Latin letters and digits. A feature written partly
// or wholly in another script (Hebrew, say) keeps too little of itself that way, so it gets a short
// stable hash of the whole text, and two such features don't share a name.
export function slugOf(feature: string): string {
  const latin = feature.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40).replace(/-$/, '')
  if (latin && !/[^\x00-\x7f]/.test(feature)) return latin
  let h = 0x811c9dc5
  for (const c of feature.trim()) h = Math.imul(h ^ c.codePointAt(0)!, 0x01000193) >>> 0
  return `${latin || 'feature'}-${h.toString(36).padStart(7, '0').slice(-7)}`
}

// Where each agent works, by absolute path (L9): a feature that names the main checkout's paths once
// drew the agents out of the worktree, and the spec landed in the person's checkout.
export const specPathOf = (run: Pick<Run, 'worktree' | 'specFile'>) => (run.worktree ? `${run.worktree}/${run.specFile}` : run.specFile)
export const whereLine = (run: Pick<Run, 'worktree' | 'slug' | 'kind'>) =>
  !run.worktree
    ? ''
    : run.kind === 'review'
      ? `The change is in the person's checkout ${run.worktree}: read it there by absolute paths, with the Read, Grep and Glob tools rather than shell commands, and change nothing. ${SHELL_LINE}`
    : `Work only in the worktree ${run.worktree}: read and edit files there by their absolute paths, with the Read, Grep, Glob and Edit tools rather than shell commands. The main checkout ${rootOf(run)} is the person's: never cd into it or change anything in it, even where the feature names a path under it; use the same path under the worktree. ${SHELL_LINE}`
// What a real run showed (2026-11-06): the agents start in the session's directory, not the worktree,
// and with no one to approve them a command that changes directory (cd, git -C) or chains several
// (&&, ;, a variable) is refused. So: one plain command per Bash call, and no git of the agent's own.
export const SHELL_LINE =
  "In Bash, one plain command per call: no cd, no git -C, no &&, ; or variables; a command like that is refused when no one is there to approve it. If one is refused, don't try it another way: say what you couldn't run."

// The repository's own rules bind the change (L1): a generated file edited by hand fails its CI.
export const RULES_LINE =
  "Read the repository's own rules first: CLAUDE.md at the worktree's root (AGENTS.md and CONTRIBUTING.md too, if there) and any CLAUDE.md in a folder the change touches. A change that breaks one (a file it says is generated, edited by hand; a check it says CI runs, that would now fail) is a blocker. Run that read-only check (a --check, a lint) when it settles it."

// The project's own test commands, so no agent guesses one (bun test, in a repo that runs claude
// plugin test): those the factory ran with their result, else those detection found.
export function testsLine(run: Pick<Run, 'checks' | 'testCommands' | 'kind'>): string[] {
  const ran = ranChecks(run as Run)
  if (ran.length) return [`The project's checks, which the factory ran itself ${run.kind === 'review' ? 'on the checkout' : 'after the last build'}: ${run.checks.map(c => `${c.cmd} ${checkWord(c)}`).join(', ')}. To run tests yourself, use exactly these commands.`]
  if (run.testCommands?.length) return [`The project's test commands (not run by the factory): ${run.testCommands.join('; ')}. To run tests yourself, use exactly these.`]
  return []
}

// What the builder said of its own work: its summary and its test run, for the reviewers and the approver (L2).
export function builderSaid(run: Pick<Run, 'summary' | 'builderTests'>): string[] {
  if (!run.summary && !run.builderTests) return []
  return [
    ...(run.summary ? [`The builder's summary: ${run.summary}`] : []),
    run.builderTests
      ? `The builder's own test run: ${run.builderTests.text}${run.builderTests.failing ? ' (it reports failures: find out whether the change caused them)' : ''}`
      : "The builder didn't say whether it ran the tests.",
  ]
}

export function specPrompt(run: Run, feedback = ''): string {
  return [
    `Feature: ${run.feature}`,
    ...(feedback ? [`The person asked for changes to your earlier spec: ${feedback}`, 'Revise the spec file and the tasks.'] : []),
    ...[whereLine(run)].filter(Boolean),
    `Write the spec to ${specPathOf(run)} (create the folder if needed).`,
    `End the spec file with a "## Code map" section, for the builder and reviewers to start from instead of searching again: each file the change touches or depends on, with the functions, types and line ranges that matter (path:start-end) and a few words on each; the signatures of the types it uses from large files (type definitions, generated code), so nobody reads those whole; and the commands that test the change. For each file the change will create, change or delete, one line on why it must. In it, list every copy of the code the change touches (the same logic in another module, a bundled and a standalone version, generated output) and mark each in or out of scope.`,
    'Then judge the size of the feature, on a line of its own:',
    'SIZE: small, medium or large',
    'small: a local change in one or two files. medium: a few files in one area, the design clear. large: it spans several modules, or needs design decisions (architecture, data model or migrations, security, concurrency), or the request leaves real questions open. The builder runs on a stronger model for a large one.',
    'Then end your answer with the task breakdown, in this exact form, 3 to 8 tasks, in any order:',
    'TASKS:',
    '1. [high] <short imperative title>',
    '2. [medium] <title> (needs 1)',
    'Priority is how much a task matters to the feature; "needs" lists the tasks it depends on.',
  ].join('\n')
}

// How the builder ends: what it changed, then its own test run on a line the factory reads.
export const BUILDER_END = [
  'End with a two-line summary of what you changed, then one line with the tests you ran and their result:',
  'TESTS: <command> -> <N passed, M failed>   (or: TESTS: none run, and why)',
]

// What a builder that stopped mid-job is told when it's sent on: it keeps its own context, so only
// to pick up where it was, after checking what it already left in the worktree.
export const resumePrompt = (why: string) =>
  `You stopped before finishing${why ? ` (${why})` : ''}. Carry on from where you stopped: check \`git status\` and \`git log\` in this worktree for what you already did, and don't redo it. Commit when done, and end as your job said: ${BUILDER_END.join(' ')}`

// A new builder on a worktree that already has work in it (the one before stopped and couldn't be
// sent on): what is there, from git, so it starts from it instead of reading its way back. `ignore`:
// files that aren't a builder's work, the spec the spec-writer left uncommitted above all (a first
// builder was once told a builder before it had stopped, over the spec alone).
export function progressNote(log: string, status: string, ignore: readonly string[] = []): string {
  const commits = log.trim().split('\n').filter(Boolean)
  const changed = status.split('\n').filter(l => l.trim() && !ignore.includes(l.slice(3).trim().replace(/^"|"$/g, '')))
  if (!commits.length && !changed.length) return ''
  return [
    'A builder before you started this job and stopped; its work is in this worktree. Start from it, check it against the spec, and do what is left; don\'t redo it.',
    ...(commits.length ? [`Its commits (newest first):`, ...commits.slice(0, 20).map(c => `- ${c}`)] : []),
    ...(changed.length ? [`Uncommitted changes:`, ...changed.slice(0, 30).map(c => `- ${c.trim()}`)] : []),
  ].join('\n')
}

// An API error no other model gets past (a spend or rate limit, quota, overload): the run waits for
// the person's Retry instead of trying the session's model at once.
export const isLimitError = (why: string) => /spend limit|rate limit|usage limit|quota|overloaded|429|529|credit/i.test(why)

// The builder's prompt: the whole job for a new builder; for the builder that built it before
// (`again`), only what to fix this round. A note is the person's own, sent back with /factory rework.
export function buildPrompt(run: Run, findings: Finding[], failed: Check[], { again = false, note = '' } = {}): string {
  // In the session goal, goal-run's ids: it numbers the tasks in its own order, not the spec's.
  const tasks = run.gate === 'goal-run' && run.goalTasks?.length ? run.goalTasks.map(t => `- ${t.id}: ${t.title}`) : run.tasks.map((t, i) => `- t${i + 1}: ${t.title}`)
  const head = again
    ? [`Another round on the change you built for: ${titleOf(run.feature, 200)}`, `Same branch ${run.branch} and worktree (${run.worktree}). Fix what follows, keep the rest as it is, and commit.`]
    : [
        `Implement the spec in ${specPathOf(run)} for: ${run.feature}`,
        `You are on branch ${run.branch}, in its own worktree. Commit your work to this branch when done.`,
        whereLine(run),
        "Follow the repository's CLAUDE.md (read it first): its rules on generated files and the commands it says to run before a commit.",
        "If a git or test command is refused, leave it: the factory commits what you leave in the worktree and runs the checks itself. Say in your TESTS line what you couldn't run.",
        `For each of the spec's Open questions, say in your closing summary how you settled it.`,
        `Start from the spec's "Code map": read the files it lists by the ranges it gives. Search (Grep) before reading anything it doesn't list, and never read a large file (type definitions, generated code, lockfiles) whole.`,
        // Marked in goal-run only when its plan is the session goal: when goal-run kept the person's own
        // goal, its t1, t2... are the person's tasks, not these.
        run.gate === 'goal-run' ? 'The tasks (in the session goal: mark each with mcp__goal-run__update as in_progress, then done):' : 'The tasks:',
        ...tasks,
      ]
  return [
    ...head,
    ...(note ? ['', `The person sent the change back: ${note}`] : []),
    ...(again ? testsLine(run) : []),
    ...(failed.length
      ? ['', 'The checks failed on your last pass. Fix them:', ...failed.map(c => `$ ${c.cmd}\n${c.tail}`)]
      : []),
    ...(findings.length
      ? ['', `Review round ${run.round} asked for changes. Fix each blocker and major finding; fix a minor one only when it's cheap:`, ...findings.map(f => `- [${f.severity}] ${f.where} ${f.text}`)]
      : []),
    '',
    ...BUILDER_END,
  ].join('\n')
}

// Why a command run rejected: it couldn't start (its program isn't installed), unless it timed out.
// "timeoutMs" in a refusal of the call itself isn't a timeout.
export const couldNotStart = (err: unknown) => !/time(d)?\s*out(?!ms)/i.test(String(err))

// The checks that actually ran: one whose program isn't installed here was skipped, not run.
export const ranChecks = (run: Pick<Run, 'checks'>) => run.checks.filter(c => !c.isMissing)
const checkWord = (c: Check) => (c.isSkipped ? 'skipped by the person, not run' : c.why ? `not run (${c.why})` : c.isMissing ? 'not installed, not run' : c.ok ? 'passed' : 'FAILED')

export function reviewPrompt(run: Run, role: Reviewer, stat: string): string {
  return [
    `Review the change for: ${run.feature}`,
    ...(run.kind === 'review'
      ? [
          `There is no spec: review the change against what it is for and against the code around it. The change is the checkout ${run.worktree} against ${run.base.slice(0, 12)}, uncommitted work included.`,
          ...(run.untracked?.length ? [`New files not yet in git (not in the diff; read them whole): ${run.untracked.join(', ')}`] : []),
        ]
      : [`The spec is ${specPathOf(run)}. The change is the commits on branch ${run.branch} since ${run.base.slice(0, 12)} (git -C ${run.worktree} diff ${run.base.slice(0, 12)}..HEAD): exactly what will be pushed.`]),
    whereLine(run),
    ...testsLine(run),
    ...(run.diffFile ? [`The whole diff is in ${run.diffFile}: read it with the Read tool (by range when it is long) instead of running git.`] : []),
    stat ? `Files changed:\n${stat}` : '',
    ...builderSaid(run),
    ...(!ranChecks(run).length && run.checksNote ? [`No checks ran for this change: ${run.checksNote} Nothing was verified by running it, so weigh the tests you read accordingly.`] : []),
    `Start from the diff${run.kind === 'review' ? '' : ` and the spec's "Code map"`}. Read a changed file whole when it is short (under about 400 lines), else around the changed lines; search before reading anything else.`,
    'Check every API field, input or type the change, or an acceptance criterion, relies on against its real definition (search for it and read the definition), not against the spec\'s wording: a criterion built on a field that doesn\'t exist is a blocker, and a test that only feeds a made-up fixture doesn\'t prove it.',
    ...(run.route?.focus.length ? ['What this diff calls for (from its files and lines, checked by the factory): look at each of these closely.', ...run.route.focus.map(f => `- ${f}`)] : []),
    ...(isExtra(role) ? [`You are the ${role} reviewer: look at ${run.extras?.find(e => e.name === role)?.focus ?? role}.`] : []),
    RULES_LINE,
    `Look only at what a ${role} review covers. Don't change any file.`,
    'Begin your answer with one line, before anything else:',
    'UNDERSTOOD: <what the change must do, in one or two sentences of your own, from the spec>',
    'End your answer with exactly:',
    'VERDICT: PASS or VERDICT: CHANGES',
    'FINDINGS:',
    '- [blocker|major|minor] <path:line> <what is wrong and why>',
    'NOT CHECKED:',
    '- <an acceptance criterion or part of the change in your area that you did not verify, and why>',
    "path:line is a line of the file itself, as Read shows it, never a line of the diff file. A finding that needs more than one line goes on, indented, under its own.",
    'A blocker or major finding means CHANGES. Write "FINDINGS: none" when there are none, and "NOT CHECKED: none" only when you verified everything in your area.',
  ].filter(Boolean).join('\n')
}

// To the skeptic: the round's blocker and major findings, numbered, and the answer format it ends with.
export function skepticPrompt(run: Run, findings: { role: Reviewer; finding: Finding }[]): string {
  return [
    `A change for: ${run.feature}`,
    run.kind === 'review'
      ? `There is no spec. The change is the checkout ${run.worktree} against ${run.base.slice(0, 12)}, uncommitted work included.`
      : `The spec is ${specPathOf(run)}. The change is on branch ${run.branch}, since ${run.base.slice(0, 12)} (git -C ${run.worktree} diff ${run.base.slice(0, 12)}..HEAD).`,
    whereLine(run),
    ...(run.diffFile ? [`The whole diff is in ${run.diffFile}: read it with the Read tool instead of running git.`] : []),
    'The reviewers asked for changes over these findings. For each, try to refute it: read the code it names, the definitions it relies on, run a read-only command if that settles it. Refute only with evidence.',
    ...findings.map((x, i) => `F${i + 1}. ${x.role} [${x.finding.severity}] ${x.finding.where} ${x.finding.text}`),
    'End your answer with one line per finding, exactly:',
    'F<n>: STANDS | REFUTED <evidence: file:line or command output> | DOWNGRADED <why it is only minor, with evidence>',
  ].join('\n')
}

// `stat`: git's list of the files the change touched, so the approver can hold them against the spec.
export function approvePrompt(run: Run, stat = ''): string {
  const reviews = run.reviews.map(r =>
    [
      `- ${r.role}: ${r.state === 'pass' ? 'PASS' : 'CHANGES'}`,
      ...(r.understood ? [`  understood: ${r.understood}`] : []),
      ...r.findings.map(f => `  - [${f.severity}] ${f.where} ${f.text}`),
      `  not checked: ${r.notChecked === undefined ? 'not said' : r.notChecked.length ? r.notChecked.join('; ') : 'none'}`,
    ].join('\n'),
  )
  return [
    `Decide on the change for: ${run.feature}`,
    `The spec is ${specPathOf(run)}; the change is on branch ${run.branch}, in the worktree ${run.worktree}.`,
    whereLine(run),
    ...builderSaid(run),
    ...(run.route?.focus.length ? ['What this diff called for:', ...run.route.focus.map(f => `- ${f}`)] : []),
    ...(run.refuted?.length ? ['Findings a skeptic refuted or downgraded with evidence (not fixed, on purpose):', ...run.refuted.map(x => `- ${x.role} [${x.finding.severity}] ${x.finding.where} ${x.finding.text}: ${x.ruling}, ${x.why}`)] : []),
    `Checks the factory ran itself, in the worktree, after the last build: ${ranChecks(run).length ? run.checks.map(c => `${c.cmd} ${checkWord(c)}`).join(', ') : `NONE RAN. ${run.checksNote || 'none configured'}`}.${ranChecks(run).length ? ' A reviewer or the builder who says it couldn\'t run one of these is covered by this result.' : ''}`,
    ...(ranChecks(run).length && run.checksNote ? [`Check notes: ${run.checksNote}`] : []),
    ...(stat ? [`Files the change touched:\n${stat}`, "Hold them against the spec's Design and Code map: a file, dependency or public interface the spec doesn't name is scope it didn't ask for. Name it in your reason, and ESCALATE unless it is plainly needed to meet a criterion."] : []),
    "Read the spec's Open questions: one the change settled by guessing, rather than the way the spec or the builder's summary says, is the person's to decide: ESCALATE.",
    "Read the repository's CLAUDE.md: a change to files it says are generated, or one that skips a check it says CI runs, is the person's to decide: ESCALATE.",
    `Review rounds: ${run.round}. The last verdicts, each with what the reviewer understood the change to be and what it says it did not check:`,
    ...reviews,
    "A reviewer whose understanding misses the spec's goal reviewed something else: ESCALATE. An acceptance criterion that no reviewer checked and no check ran for is unverified: ESCALATE, naming it. The builder reporting failing tests: ESCALATE, unless a check above ran those tests and passed.",
    'APPROVE when every acceptance criterion is met and verified and no blocker or major finding is left; otherwise ESCALATE to the person.',
    ...(!ranChecks(run).length ? ['No check ran: an APPROVE goes to the person as an escalation, since nothing was verified by running it. Say in your reason what the reviews did verify.'] : []),
    'End with exactly:',
    'DECISION: APPROVE or DECISION: ESCALATE',
    'REASON: <one line>',
  ].join('\n')
}

// To the main Claude: put the spec's tasks into goal-run's plan, where the person approves them.
export function planPrompt(run: Run): string {
  const tasks = JSON.stringify(run.tasks.map(t => ({ title: t.title, priority: t.priority, ...(t.dependsOn.length ? { dependsOn: t.dependsOn } : {}) })))
  return [
    `The factory's spec for ${JSON.stringify(run.feature)} is in ${run.specFile}.`,
    `Call mcp__goal-run__plan now with goal ${JSON.stringify(run.feature)}, source "${FACTORY_SOURCE}", and exactly these tasks, unchanged:`,
    tasks,
    "Then stop: the factory's builder does the work. Don't start the tasks or edit any file.",
  ].join('\n')
}

// To the main Claude, once approved: the PR, through whatever GitHub access the session has.
// The branch the PR goes into: the one the run is built on, without its remote's name.
export const CONTROL_TOOL_NAME = 'mcp__factory__control'
export const prBase = (run: Pick<Run, 'baseRef'>) => run.baseRef?.replace(/^(origin|upstream)\//, '') ?? ''

// How the PR is opened, as commands: what the person runs when the feature says not to push.
export const prCommands = (run: Run) => [
  `git -C ${run.worktree} push -u origin ${run.branch}`,
  `gh pr create --head ${run.branch}${prBase(run) ? ` --base ${prBase(run)}` : ''} --title ${JSON.stringify(titleOf(run.feature, 70))} --body-file <the body below, saved to a file>`,
]

export function prPrompt(run: Run, reason: string): string {
  const minor = run.reviews.flatMap(r => r.findings.filter(f => f.severity === 'minor').map(f => `- ${r.role}: ${f.where} ${f.text}`))
  const unverified = run.reviews.flatMap(r => (r.notChecked ?? []).map(t => `- ${r.role}: ${t}`))
  const noPush = forbidsPush(run.feature)
  return [
    `The factory run "${run.feature}" is approved${reason ? ` (${reason})` : ''}.`,
    ...(noPush
      ? [
          "The feature says not to push, so don't push and don't open the PR. Show the person these commands to run themselves, and the PR body below:",
          ...prCommands(run).map(c => `  ${c}`),
          `If the person opens it and gives you the link, call ${CONTROL_TOOL_NAME} with action "pr-opened" and the link as url.`,
        ]
      : [
          `Push branch ${run.branch} (git -C ${run.worktree} push -u origin ${run.branch}) and open a pull request from it${prBase(run) ? ` into ${prBase(run)} (the branch it is built on; not the repository's default branch)` : ''}.`,
          `Once it is open, call ${CONTROL_TOOL_NAME} with action "pr-opened" and the PR's link as url: until then the factory shows the PR as requested, not opened. If you can't open it, tell the person why, with these commands: ${prCommands(run).join(' && ')}.`,
        ]),
    `Title it after the feature. In the body: what it does (from ${run.specFile}), the checks (${run.checks.map(c => `${c.cmd} ${c.isSkipped ? '– skipped' : c.isMissing ? '– not installed' : c.ok ? '✓' : '✗'}`).join(', ') || 'none ran'}), and ${run.round} review round${run.round === 1 ? '' : 's'}: ${run.reviews.map(r => `${r.role} ${r.state === 'pass' ? 'PASS' : 'CHANGES'}`).join(', ')}.`,
    ...(run.builderTests ? [`The builder's own test run: ${run.builderTests.text}.`] : []),
    ...(minor.length ? ['List these minor findings under "Not fixed":', ...minor] : []),
    ...(unverified.length ? ['List what the reviewers said they did not check under "Not verified":', ...unverified] : []),
    ...(run.followupId ? [`Once the PR is open, call mcp__followups__done with id "${run.followupId}" and the PR's link as the note: the run came from that to-do item.`] : []),
    ...(run.skipped?.length ? [`The factory left these new files out of its commits (dependencies, build output or credentials); don't add them: ${run.skipped.join(', ')}.`] : []),
  ].join('\n')
}

// ---------- a run ----------

// The worktrees sit inside the repository, in .factory/ (kept out of git): within the session's
// working directory, so the agents' edits get the same permissions and sandbox as the person's.
export const worktreeOf = (root: string, slug: string) => `${root.replace(/[\\/]+$/, '')}/.factory/${slug}`
// The main repository a run's worktree belongs to: worktreeOf turned back.
export const rootOf = (run: { worktree: string; slug: string }) => run.worktree.slice(0, -`/.factory/${run.slug}`.length)
// Beside the worktree, never in it: a slug has no dot, so no run's worktree is named so.
export const recordOf = (root: string, slug: string) => `${root.replace(/[\\/]+$/, '')}/.factory/${slug}.record`

// An agent's closing lines: the builder ends with a two-line summary of what it changed.
export function lastLines(text: string, n: number): string {
  return text.split('\n').map(l => l.trim()).filter(Boolean).slice(-n).join(' ').slice(0, 300)
}

// What never goes into a commit, even where the project's .gitignore misses it: installed dependencies
// and credentials. Narrow on purpose: a match the builder committed stops the run. Build output
// (dist/, build/) isn't on it: a folder of that name can be source (cmd/build/), and one that is
// output is the .gitignore's to keep out. A sample .env (.env.example) and a key or certificate among
// test fixtures are files a change may well add.
const DEPENDENCIES = /(^|\/)(node_modules|\.venv|venv|__pycache__)(\/|$)/
const ENV_FILE = /(^|\/)\.env(\.[^/]*)?$/
const SAMPLE_ENV = /(^|\/)\.env\.(example|sample|template|dist)$/i
const KEY_FILE = /\.(pem|key|p12|pfx)$/i
const TEST_DIR = /(^|\/)(tests?|__tests__|spec|fixtures|__fixtures__|testdata)\//i
export const neverCommit = (path: string) =>
  DEPENDENCIES.test(path) || (ENV_FILE.test(path) && !SAMPLE_ENV.test(path)) || (KEY_FILE.test(path) && !TEST_DIR.test(path))

// The files left out, as a person reads them: a file inside an excluded folder (node_modules/)
// as that folder, once, so a whole install doesn't list file by file.
export function leftOut(paths: readonly string[]): string[] {
  const out: string[] = []
  for (const p of paths) {
    const parts = p.split('/')
    let shown = p
    for (let i = 1; i < parts.length; i++) {
      const dir = `${parts.slice(0, i).join('/')}/`
      if (neverCommit(dir)) {
        shown = dir
        break
      }
    }
    if (!out.includes(shown)) out.push(shown)
  }
  return out
}

// The untracked files in `git status --porcelain -z -uall` output: each file on its own (never a
// folder, which would stage the .env or node_modules inside it), unquoted, non-ASCII names as they
// are. A rename or copy entry carries its old path as the next field, skipped here.
export function untrackedOf(porcelainZ: string): string[] {
  const fields = porcelainZ.split('\0')
  const out: string[] = []
  for (let i = 0; i < fields.length; i++) {
    const f = fields[i]!
    if (f.startsWith('?? ')) out.push(f.slice(3))
    else if (/^[RC]/.test(f)) i++
  }
  return out
}

export const reviewOf = (role: Reviewer): Review => ({ role, state: 'wait', findings: [], tokens: 0, round: 0, agentId: null })

// A review run: the reviewers on the change in the person's checkout, against `base`.
export function newReview(focus: string, at: number, base: string, root: string, slug: string, untracked: string[] = []): Run {
  const r = newRun(focus, at, base, root, slug)
  const skip = { state: 'skip' as StepState, tokens: 0 }
  return {
    ...r,
    kind: 'review',
    // The checks first (the person lets the found commands run, or not), then the reviewers.
    phase: 'checks',
    round: 0,
    branch: '',
    worktree: root.replace(/[\\/]+$/, ''),
    specFile: '',
    steps: { spec: skip, builder: skip, checks: { state: 'wait', tokens: 0 }, approver: skip },
    note: 'running the checks before the review',
    gate: 'factory',
    ...(untracked.length ? { untracked: untracked.slice(0, 40) } : {}),
  }
}

// What the main Claude is told once a review run's reviewers (and the skeptic) are done.
export function reviewDonePrompt(run: Run): string {
  const standing = run.reviews.flatMap(r => r.findings.map(f => ({ role: r.role, f })))
  const fix = standing.filter(x => x.f.severity !== 'minor')
  const minor = standing.filter(x => x.f.severity === 'minor')
  const unverified = run.reviews.flatMap(r => (r.notChecked ?? []).map(t => `- ${r.role}: ${t}`))
  return [
    `The factory's reviewers (${run.reviews.map(r => reviewerLabel(r.role)).join(', ')}) reviewed the change in ${run.worktree} against ${run.base.slice(0, 12)}${run.feature ? ` (${titleOf(run.feature, 120)})` : ''}.`,
    ...(fix.length
      ? ['Fix each of these in the checkout, then say what you changed:', ...fix.map(x => `- ${x.role} [${x.f.severity}] ${x.f.where} ${x.f.text}`)]
      : ['No blocker or major finding.']),
    ...(minor.length ? ['Minor, fix when cheap:', ...minor.map(x => `- ${x.role} ${x.f.where} ${x.f.text}`)] : []),
    ...(run.refuted?.length ? ['A skeptic refuted or downgraded these with evidence (leave them):', ...run.refuted.map(x => `- ${x.role} ${x.finding.where} ${x.finding.text}: ${x.ruling}, ${x.why}`)] : []),
    ...(unverified.length ? ['What the reviewers say they did not check:', ...unverified] : []),
    `Their words: ${run.record ?? ''}/. Don't start another review unless the person asks.`,
  ].join('\n')
}

export function newRun(feature: string, at: number, base: string, root: string, slug = slugOf(feature)): Run {
  const step = (): { state: StepState; tokens: number } => ({ state: 'wait', tokens: 0 })
  return {
    feature: feature.trim(),
    slug,
    phase: 'spec',
    round: 0,
    checkRound: 0,
    startedAt: at,
    base,
    branch: `factory/${slug}`,
    worktree: worktreeOf(root, slug),
    record: recordOf(root, slug),
    specFile: `docs/specs/${slug}.md`,
    tasks: [],
    steps: { spec: { state: 'run', tokens: 0 }, builder: step(), checks: step(), approver: step() },
    checks: [],
    reviews: REVIEWERS.map(role => reviewOf(role)),
    agents: {},
    note: 'writing the spec',
    blocked: null,
    gate: 'goal-run',
    setupDone: false,
  }
}

export const isLive = (p: Phase) => p !== 'done' && p !== 'stopped'
// Waiting for the person, not for an agent or a command.
export const waitsOnPerson = (p: Phase) => p === 'plan' || p === 'ready' || p === 'needs-human'
// Waiting for the person: a phase that waits on them, or the question before the checks run.
export const waitsOnYou = (r: Pick<Run, 'phase' | 'isAskingChecks'>) => waitsOnPerson(r.phase) || !!r.isAskingChecks

const mmss = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// No action from the run's agent for this long reads as quiet: the band says so, in orange.
export const QUIET_MS = 5 * 60_000
const AGENT_PHASES: Phase[] = ['spec', 'build', 'review', 'approve']
export const isQuiet = (run: Run, now: number) =>
  AGENT_PHASES.includes(run.phase) && now - (run.activity?.at ?? run.phaseSince ?? now) > QUIET_MS

// Where the run is, in a line: during the checks, which command runs and for how long; while an agent
// works, its latest action and how long ago; a quiet one, for how long it has been quiet.
export function statusOf(run: Run, now: number): string {
  const c = run.phase === 'checks' && !run.isAskingChecks ? run.checking : null
  if (c) return `${c.isSetup ? 'installing' : 'checks'} ${c.index}/${c.total} · ${c.cmd} · ${mmss(now - c.since)}`
  if (!AGENT_PHASES.includes(run.phase)) return run.note
  const last = run.activity?.at ?? run.phaseSince
  if (last === undefined) return run.note
  if (isQuiet(run, now)) return `${run.note} · no activity for ${mmss(now - last)}`
  return run.activity?.calls ? `${run.note} · ${run.activity.text} · ${mmss(now - run.activity.at)} ago` : run.note
}

// What a tool call of the run's agent reads as, in a few words.
export function activityText(tool: string, input: Record<string, unknown>): string {
  const base = (p: unknown) => String(p ?? '').split(/[\\/]/).filter(Boolean).pop() ?? ''
  const clip = (t: string) => (t.length > 60 ? `${t.slice(0, 59)}…` : t)
  switch (tool) {
    case 'Read': return clip(`reading ${base(input.file_path)}`)
    case 'Write': return clip(`writing ${base(input.file_path)}`)
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit': return clip(`editing ${base(input.file_path ?? input.notebook_path)}`)
    case 'Bash': return clip(`running ${String(input.description ?? String(input.command ?? '').split('\n')[0])}`)
    case 'Grep':
    case 'Glob': return clip(`searching ${String(input.pattern ?? '')}`)
    case 'Skill': return clip(`loading the ${String(input.skill ?? '')} skill`)
    default: return clip(`using ${tool.replace(/^mcp__[^_]+__/, '')}`)
  }
}

// How far along the run is, 0 to 100: by its step, and within a step by what can be counted (a check's
// place, the reviewers done) or, for an agent, by its tool calls, creeping toward the step's end.
export function progressOf(run: Run): number {
  const creep = (span: number) => {
    const n = run.activity?.calls ?? 0
    return span * (n / (n + 15))
  }
  switch (run.phase) {
    case 'spec': return Math.round(2 + creep(13))
    case 'plan': return 15
    case 'build': return Math.round((run.round > 0 ? 50 : 20) + creep(run.round > 0 ? 8 : 25))
    case 'checks': return Math.round(45 + (run.checking && !run.isAskingChecks ? (15 * (run.checking.index - 1)) / run.checking.total : 0))
    case 'review': {
      const mine = run.reviews.filter(x => x.round === run.round)
      return Math.round(60 + (25 * mine.filter(x => x.state !== 'run').length) / Math.max(1, mine.length))
    }
    case 'approve': return Math.round(85 + creep(10))
    case 'ready': return 95
    case 'done': return 100
    default: return run.lastProgress ?? 0
  }
}

export const progressBar = (pct: number, cells = 12) => {
  const full = Math.round((Math.max(0, Math.min(100, pct)) / 100) * cells)
  return `${'▰'.repeat(full)}${'▱'.repeat(cells - full)}`
}

// Everything about the run, as text: what the main Claude reads from the status tool to say where a run
// is, what it waits on and where it failed, and where to read more.
export function statusReport(run: Run, now: number, recordFiles: string[] = []): string {
  const findings = run.reviews.filter(x => x.round === run.round && x.findings.length)
  return [
    `Factory run: ${run.feature}`,
    `Phase: ${run.phase}${run.blocked ? ` (blocked on ${run.blocked.on})` : ''} · ${progressOf(run)}% · ${statusOf(run, now)}${run.phaseSince ? ` · in this phase for ${mmss(now - run.phaseSince)}` : ''}`,
    run.kind === 'review'
      ? `A review of the checkout ${run.worktree} against ${run.baseRef ? `${run.baseRef} (${run.base.slice(0, 12)})` : run.base.slice(0, 12)}: reviewers only, no spec or build.`
      : `Branch ${run.branch}, worktree ${run.worktree}, based on ${run.baseRef ? `${run.baseRef} (${run.base.slice(0, 12)})` : run.base.slice(0, 12)}; spec ${run.specFile}.`,
    ...(run.activity ? [`Last agent action: ${run.activity.role} ${run.activity.text}, ${mmss(now - run.activity.at)} ago (${run.activity.calls} tool calls this step).`] : []),
    `Steps: ${(Object.keys(run.steps) as (keyof Run['steps'])[]).map(k => `${k} ${run.steps[k].state}`).join(', ')}; reviews round ${run.round}: ${run.reviews.map(x => `${x.role} ${x.state}`).join(', ')}.`,
    ...(run.stat ? [`Changed: ${run.stat}`] : []),
    ...(run.builderTests ? [`Builder's own test run: ${run.builderTests.text}${run.builderTests.failing ? ' (failures reported)' : ''}`] : []),
    ...(run.pr ? [`PR: ${run.pr.state === 'opened' ? `opened, ${run.pr.url}` : run.pr.state === 'handed' ? 'handed to the person as commands (the feature says not to push)' : 'requested; not reported open yet'}`] : []),
    ...(run.checks.length ? ['Checks:', ...run.checks.map(c => `- ${c.isSkipped ? 'skipped' : c.why ? `not run (${c.why})` : c.isMissing ? 'not installed' : c.isTimedOut ? 'TIMED OUT' : c.ok ? 'passed' : 'FAILED'}: ${c.cmd}${c.tail ? `\n${c.tail.split('\n').slice(-10).map(l => `    ${l}`).join('\n')}` : ''}`)] : []),
    ...(run.checksNote ? [`Checks note: ${run.checksNote}`] : []),
    ...(findings.length ? ['Findings this round:', ...findings.flatMap(x => x.findings.map(f => `- ${x.role} [${f.severity}] ${f.where} ${f.text}`))] : []),
    ...(waitsOnYou(run) ? [`Waits on the person: ${run.note}`] : []),
    ...(run.record ? [`What each step said: ${run.record}/${recordFiles.length ? ` (${recordFiles.join(', ')})` : ''}`] : []),
    ...statsReport(run, now).map(l => `Stats: ${l}`),
    nextActionsText(nextActionsOf(run, now)),
  ].join('\n')
}

// What can be done about the run now, and by whom: the main Claude through its tools (only when the
// person asks, or a step is plainly stuck), or the person, whose decisions these are. The status
// tool lists them, so Claude doesn't guess (a Retry on an escalation, say).
export type NextAction = { action: string; by: 'claude' | 'person'; how: string }

export function nextActionsOf(run: Run | null, now: number): NextAction[] {
  const C = CONTROL_TOOL_NAME
  const start: NextAction = { action: 'start', by: 'claude', how: 'mcp__factory__start with the feature, when the person asks for a run' }
  const stop: NextAction = { action: 'stop', by: 'claude', how: `${C} action "stop", only when the person asks (or /factory stop)` }
  if (!run) return [start]
  if (run.phase === 'stopped') return [start]
  if (run.phase === 'done') {
    if (run.pr?.state === 'requested') return [{ action: 'pr-opened', by: 'claude', how: `once you opened the PR: ${C} action "pr-opened" with its link as url` }, start]
    if (run.pr?.state === 'handed') return [{ action: 'pr-opened', by: 'claude', how: `once the person says they opened it and gives the link: ${C} action "pr-opened"` }, start]
    return [start]
  }
  const rework: NextAction = { action: 'rework', by: 'person', how: '/factory rework <what to change>: sends the change back to the builder' }
  switch (run.phase) {
    case 'plan':
      return [
        run.gate === 'goal-run'
          ? { action: 'approve-plan', by: 'person', how: "in goal-run's dialog or the Goal pane (/session-goal); not yours to approve" }
          : { action: 'approve-plan', by: 'person', how: "/factory approve, or Approve plan in the factory's band; not yours to approve" },
        stop,
      ]
    case 'checks':
      if (run.isAskingChecks) return [{ action: 'answer-checks', by: 'person', how: "the open question on which commands to run; not yours to answer" }, stop]
      return [...(run.checking ? [{ action: 'skip-check', by: 'claude' as const, how: `${C} action "skip-check", when ${run.checking.cmd} hangs` }] : []), stop]
    case 'ready':
      return [{ action: 'open-pr', by: 'person', how: '/factory approve, or Open PR in the band; not yours to approve' }, rework, stop]
    case 'needs-human': {
      const b = run.blocked
      if (b?.on === 'checks' && run.askedChecks)
        return [
          { action: 'checks-ok', by: 'person', how: `/factory checks-ok: runs the commands the factory found (${run.askedChecks.replace(/ @ \S*$/, '')}); not yours to allow` },
          { action: 'retry', by: 'claude', how: `${C} action "retry": asks the person the question again` },
          stop,
        ]
      if (b?.on === 'escalate') return [{ action: 'approve-pr', by: 'person', how: `/factory approve, or Approve PR, over the approver's escalation; not yours to approve` }, rework, stop]
      if (b?.on === 'base') return [{ action: 'base', by: 'person', how: '/factory base <branch>: the branch the work is on top of' }, stop]
      return [
        { action: 'retry', by: 'claude', how: `${C} action "retry" (or /factory retry): runs the step that stopped again${b?.on === 'checks' || b?.on === 'setup' ? ', once the cause is fixed' : ''}` },
        ...(run.steps.builder.state !== 'wait' ? [rework] : []),
        stop,
      ]
    }
    default:
      return [
        ...(isQuiet(run, now) ? [{ action: 'abandon-agent', by: 'claude' as const, how: `${C} action "abandon-agent": the agent has been quiet for long; Retry then starts a new one` }] : []),
        ...(run.phase === 'build' || run.phase === 'review' ? [{ action: 'add-reviewers', by: 'claude' as const, how: `${C} action "add-reviewers", only when the change needs that look` }] : []),
        stop,
      ]
  }
}

export const nextActionsText = (list: NextAction[]) =>
  ['Next actions:', ...list.map(a => `- ${a.action} (${a.by === 'claude' ? 'you' : 'the person'}): ${a.how}`)].join('\n')

// The doctor's findings, a line each: ok, a warning (the run works, with a catch) or a blocker.
export type DoctorItem = { level: 'ok' | 'warn' | 'block'; text: string }
export function doctorReport(items: DoctorItem[]): string {
  const mark = { ok: '✓', warn: '!', block: '✗' } as const
  const blocked = items.filter(i => i.level === 'block').length
  const warned = items.filter(i => i.level === 'warn').length
  return [
    `Factory doctor: ${blocked ? `${blocked} blocker${blocked === 1 ? '' : 's'}: a run can't start until ${blocked === 1 ? 'it is' : 'they are'} fixed` : warned ? `a run can start; ${warned} thing${warned === 1 ? '' : 's'} to know` : 'ready to run'}.`,
    ...items.map(i => `${mark[i.level]} ${i.text}`),
  ].join('\n')
}

// How the run went, in a few lines: for its record (stats.md) and the status.
export function statsReport(run: Run, now: number): string[] {
  const s = run.stats
  const calls = s ? Object.entries(s.toolCalls).map(([k, v]) => `${k} ${v}`).join(', ') : ''
  const found = run.reviews.flatMap(r => r.findings)
  const by = (sev: string) => found.filter(f => f.severity === sev).length
  return [
    `Time: ${mmss(now - run.startedAt)} from start${run.kind === 'review' ? ' (a review run)' : ''}.`,
    `Iterations: ${run.kind === 'review' ? 'review only' : `${s?.builderStarts ?? 0} builder start${s?.builderStarts === 1 ? '' : 's'}`}, ${run.round} review round${run.round === 1 ? '' : 's'}${run.checkRound ? `, ${run.checkRound} fix pass${run.checkRound === 1 ? '' : 'es'} for red checks` : ''}.`,
    `Findings this round: ${by('blocker')} blocker, ${by('major')} major, ${by('minor')} minor; refuted by the skeptic so far: ${run.refuted?.length ?? 0}.`,
    `Tool calls the factory saw: ${calls || 'none'}; refused by its guard: ${s?.guardRefused ?? 0}.`,
    `Answers missing a marker their prompt asks for: ${s?.formatMisses.length ? s.formatMisses.join('; ') : 'none'}.`,
  ]
}

export const tokensOf = (run: Run) => Object.values(run.steps).reduce((n, s) => n + s.tokens, 0) + run.reviews.reduce((n, r) => n + r.tokens, 0) + (run.skepticTokens ?? 0)
export const tok = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n}`)

// The findings the builder must still address: every finding of the reviewers that asked for changes.
export const openFindings = (reviews: Review[]) => reviews.filter(r => r.state === 'changes').flatMap(r => r.findings)
