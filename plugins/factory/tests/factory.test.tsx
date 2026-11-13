import { describe, expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

import { applyRulings, changedOf, diffLines, forbiddenCommand, forbiddenInReview, forbiddenTool, routeReview } from '../hooks/route'
import { extrasFrom, LENSES } from '../hooks/flow'
import { parseBuilderTests as builderTestsOf, nextActionsOf, forbidsPush, parseBuilderTests, parseNotChecked, parseUnderstood, summaryOf } from '../hooks/flow'
import { cleanFeature, couldNotStart, detectChecks, detectSetup, leftOut, neverCommit, slugOf, untrackedOf, modelsFor, parseDecision, parseSize, parseSkills, progressNote, titleOf, parseTasks, parseVerdict, planPrompt, specPrompt, splitChecks } from '../hooks/flow'
import { factoryArgs, goalPrompt, startLine, factoryPlanApprovedArgs, factoryPlanResultArgs, PLAN_APPROVED_FOR_FACTORY, planApprovedForFactory, PLAN_KEPT_FOR_FACTORY, planChangesForFactory } from '../hooks/texts'

const PLAN = 'mcp__goal-run__plan'

const BAND = {
  plugin: 'factory',
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 12, bodyColumns: 120, scroll: { offset: 0, bodyRows: 11 }, view: {} },
} as const

const PANE = {
  plugin: 'factory',
  component: 'Pane',
  requestId: 'factory',
  props: { title: 'Factory', isFocused: false, bodyColumns: 90, placement: 'dock', scroll: { offset: 0, bodyRows: 60 }, view: {} },
} as const

const SPEC_ANSWER = 'Wrote docs/specs/rate-limiter.md.\nTASKS:\n1. [high] Token bucket core\n2. [high] Middleware with Retry-After (needs 1)\n3. [medium] Tests for bursts (needs 1, 2)'
const PASS = 'Looked at the diff.\nVERDICT: PASS\nFINDINGS:\n- [minor] src/limit.ts:4 a name could be clearer'
const CHANGES = 'VERDICT: CHANGES\nFINDINGS:\n- [major] src/mw.ts:12 Retry-After is in ms, not seconds'

type Spawned = { id: string; subagentType: string; prompt: string; description: string; cwd?: string; model?: string }

// The engine beneath: git and the checks, the agents the factory starts, its prompts, the commands there are.
// `fails`: how many non-git commands fail first (setup and checks alike). `worktree`: the stderr of
// each failing `git worktree add`, in turn. `dirty`: the builder left uncommitted work.
function engine(on: On, { hold = '', goalRun = true, fails = 0, files = ['package.json', 'node_modules'], pkg = '{"scripts":{"test":"vitest"}}', denyType = false, worktree = [] as string[], dirty = false, commitFails = false, answers = [] as string[], delivers = false, skills = '', keepsGoal = false, planResult = PLAN_APPROVED_FOR_FACTORY, checksOk = 'Run them' as string | null, missing = [] as string[], noRepo = false, stagedNew = [] as string[], committedNew = [] as string[], historyFails = false, historyOut = null as string | null, holdAsk = false, baseGone = false, branch = '', changedFiles = '', outputs = {} as Record<string, { exitCode: number; stdout: string; stderr: string }>, setupMakes = [] as string[], mergeBase = '', reviewChange = false, newFiles = [] as string[], holdSkeptic = false } = {}) {
  // Files the install writes in the worktree (`setupMakes`, a lockfile npm install made): untracked from then on.
  const made: string[] = []
  const spawned: Spawned[] = []
  const ran: string[] = []
  const limits: Record<string, number> = {}
  // The last commit of the files that define the checks: a test moves it to change them.
  let configCommit = 'c0'
  const sent: string[] = []
  const toasts: string[] = []
  const written: Record<string, string> = {}
  // `hold`: that command waits until the test releases it, so the test can act meanwhile (a trailing * holds
  // the first command that starts with the rest).
  let release = () => {}
  const held = new Promise<void>(r => (release = r))
  let failing = fails
  const worktreeErrs = [...worktree]
  const clock = mock.clock(on, { now: Date.UTC(2026, 9, 25, 9) })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.root', () => ({ value: '/repo' }))
  on('command.register', (_, e) => ({ value: { command: e.name } }) as never)
  on('tool.register', (_, e) => ({ value: { tool: `mcp__factory__${e.name}` } }) as never)
  const registered: { name: string; tools?: string[] }[] = []
  on('agent.register', (_, e) => {
    registered.push({ name: e.name, ...(e.tools ? { tools: [...e.tools] } : {}) })
    return { value: { agent: `factory:${e.name}` } } as never
  })
  // A message to an agent of the session: delivered (it resumes), or not, when `delivers` is off.
  const sends: { to: unknown; text: string }[] = []
  on('session.send', (_, e) => {
    sends.push({ to: e.to, text: e.text })
    return (delivers ? { isDelivered: true } : { isDelivered: false, reason: 'no such agent' }) as never
  })
  on('command.list', () => ({ value: goalRun ? [{ name: 'session-goal', description: 'g', source: 'plugin' }] : [] }) as never)
  // The mod's own spawn arrives in the Agent tool's words (subagent_type).
  on('agent.spawn', async (_, e) => {
    const a = e as unknown as { subagentType?: string; subagent_type?: string; prompt: string; description: string; cwd?: string; model?: string }
    const type = a.subagentType ?? a.subagent_type ?? ''
    if (denyType && type.startsWith('factory:')) return { deny: 'unknown agent type' } as never
    // `holdSkeptic`: the skeptic's start waits until the test releases it, then fails (its general-purpose
    // fallback too), so the test can act while it is under way.
    if (holdSkeptic && type === 'factory:skeptic') {
      await held
      return { deny: 'no capacity' } as never
    }
    if (holdSkeptic && type === 'general-purpose' && a.prompt.includes('You are the skeptic')) return { deny: 'no capacity' } as never
    const id = `a${spawned.length + 1}`
    spawned.push({ id, subagentType: type, prompt: a.prompt, description: a.description, cwd: a.cwd, ...(a.model ? { model: a.model } : {}) })
    return { model: 'm', agentId: id } as never
  })
  // The kit answers a mod's own spawn itself, without an agentId: the mod finds its agent in the list.
  on('agent.list', () => ({ value: spawned.map(s => ({ id: s.id, description: s.description, type: s.subagentType, status: 'running' })) }) as never)
  const ok = (stdout = '') => ({ value: { exitCode: 0, stdout, stderr: '' } }) as never
  on('process.run', async (_, e) => {
    const cmd = e.argv.join(' ')
    ran.push(cmd)
    limits[cmd] = (e as { init?: { timeoutMs?: number } }).init?.timeoutMs ?? 0
    if (cmd === hold || (hold.endsWith('*') && cmd.startsWith(hold.slice(0, -1)))) await held
    // A review of the checkout: where the branch left origin's default branch, and the change since it.
    if (cmd === 'git merge-base HEAD origin/HEAD' && mergeBase) return ok(`${mergeBase}\n`)
    if (cmd.startsWith('git diff --quiet ')) return { value: { exitCode: reviewChange ? 1 : 0, stdout: '', stderr: '' } } as never
    if (cmd === 'git ls-files --others --exclude-standard -z') return ok(newFiles.join('\0'))
    if (mergeBase && cmd === `git diff ${mergeBase}`) return ok('diff --git a/src/mw.ts b/src/mw.ts\n+const token = req.query.token\n')
    if (cmd === 'git rev-parse --show-toplevel') return noRepo ? ({ value: { exitCode: 128, stdout: '', stderr: 'fatal: not a git repository' } } as never) : ok('/repo\n')
    if (cmd === 'git rev-parse HEAD') return ok('abc123\n')
    if (cmd.startsWith('git worktree add')) {
      const err = worktreeErrs.shift()
      return err ? ({ value: { exitCode: 128, stdout: '', stderr: err } } as never) : ok()
    }
    if (cmd.startsWith('git diff --stat')) return ok(' src/mw.ts | 40 +++\n 1 file changed')
    if (cmd === 'git diff abc123 HEAD') return ok('diff --git a/src/mw.ts b/src/mw.ts\n+export const limit = 10\n')
    // New files in the index (`stagedNew`, the builder's own git add), and new files committed since the base.
    if (cmd === 'git diff --cached --no-renames --name-only --diff-filter=A -z') return ok(stagedNew.join('\0'))
    // The branch history's added files, commit by commit (`committedNew`, all in one commit, c1000…),
    // a scan that fails (`historyFails`), or what the scan prints, as given (`historyOut`).
    if (cmd === 'git log --no-show-signature --no-renames --diff-merges=first-parent --diff-filter=A --name-only -z --format=%x00%H abc123..HEAD') {
      if (historyFails) return { value: { exitCode: 128, stdout: '', stderr: "fatal: bad revision 'abc123..HEAD'" } } as never
      if (historyOut !== null) return ok(historyOut)
      return ok(committedNew.length ? `\0${'c1'.padEnd(40, '0')}\0\n${committedNew.join('\0')}\0` : '')
    }
    if (cmd === 'git status --porcelain' || cmd === 'git status --porcelain -uall') return ok(dirty ? ' M src/mw.ts\n?? src/limit/new.ts\n?? node_modules/\n?? .env\n?? certs/server.key\n' : '')
    // -z -uall: each untracked file on its own, NUL-separated, unquoted (a new folder's .env too).
    if (cmd === 'git status --porcelain -z -uall' && !dirty) return ok(made.map(f => `?? ${f}\0`).join(''))
    if (cmd === 'git status --porcelain -z -uall') return ok(dirty ? [' M src/mw.ts', '?? src/limit/new.ts', '?? src/limit/שלום.ts', '?? app/.env', '?? app/index.js', '?? node_modules/x/a.js', '?? .env', '?? certs/server.key', 'R  src/b.ts', 'src/a.ts', ''].join('\0') : '')
    if (cmd.startsWith('git log -1 --format=%H HEAD --')) return ok(`${configCommit}\n`)
    if (cmd.startsWith('git diff --name-only abc123 HEAD --')) return ok(configCommit === 'c0' ? '' : 'package.json\n')
    if (cmd === 'git diff --cached --quiet') return { value: { exitCode: dirty ? 1 : 0, stdout: '', stderr: '' } } as never
    if (cmd === 'git rev-parse --git-path info/exclude') return ok('.git/info/exclude\n')
    if (cmd.startsWith('git commit') && commitFails) return { value: { exitCode: 1, stdout: '', stderr: 'Please tell me who you are.' } } as never
    // The checkout's branch, and a builder that replaced the branch's history (`baseGone`): its base is no
    // longer under HEAD; origin/pr-106 is, at def456.
    if (cmd === 'git rev-parse --abbrev-ref HEAD') return ok(`${branch || 'HEAD'}\n`)
    if (cmd === 'git merge-base --is-ancestor abc123 HEAD') return { value: { exitCode: baseGone ? 1 : 0, stdout: '', stderr: '' } } as never
    if (cmd.startsWith('git for-each-ref')) return ok('origin/pr-106\nfactory/rate-limiter\norigin/HEAD\nmain\n')
    if (cmd === 'git rev-parse --verify --quiet origin/pr-106^{commit}') return ok('def456\n')
    if (cmd.startsWith('git rev-parse --verify')) return { value: { exitCode: 1, stdout: '', stderr: '' } } as never
    // The branch's changed files for the review route (`changedFiles`, name-status -z).
    if (cmd.startsWith('git diff --name-status -z')) return ok(changedFiles)
    if (cmd.startsWith('git ')) return ok()
    // `outputs`: what a command answers, as given.
    if (outputs[cmd]) return { value: outputs[cmd] } as never
    if ((cmd === 'npm install' || cmd === 'npm ci') && setupMakes.length) made.push(...setupMakes.filter(f => !made.includes(f)))
    if (missing.includes(cmd)) throw new Error(`spawn ${e.argv[0]} ENOENT`)
    if (cmd === 'sh-missing') return { value: { exitCode: 127, stdout: '', stderr: 'sh: vitest: not found' } } as never
    if (failing > 0) {
      failing--
      return { value: { exitCode: 1, stdout: 'FAIL src/mw.test.ts\n  expected 429', stderr: '' } } as never
    }
    return ok('ok')
  })
  on('fs.read', (_, e) => {
    if (e.path.endsWith('package.json')) return { value: pkg } as never
    if (e.path in written) return { value: written[e.path] } as never
    // The spec the agent wrote: a file the engine has, with no commands in it.
    if (/\/docs\/specs\/.+\.md$/.test(e.path)) return { value: '# Spec' } as never
    throw new Error('ENOENT')
  })
  on('fs.write', (_, e) => {
    written[e.path] = e.text
    return { value: undefined } as never
  })
  on('fs.list', () => ({ value: files.map(name => ({ name, kind: 'file' })) }) as never)
  on('config.list', () => ({ value: [{ key: 'theme', value: 'light' }] }) as never)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', (_, e) => {
    toasts.push(String(e.text))
    return { value: undefined } as never
  })
  on('prompt.submit', (_, e) => {
    sent.push(e.text)
    return { text: e.text, context: e.context }
  })
  on('turn.complete', (_, e) => ({ text: e.answer }) as never)
  on('classic.PostToolUse', () => ({}) as never)
  on('turn.step', async function* (_, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn', usage: { model: 'm', input_tokens: 1000, output_tokens: 500, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } as never
  })
  // goal-run's plan tool, as it answers for a factory plan the person approved.
  on('tool.call', { tool: PLAN }, () => ({ result: keepsGoal ? PLAN_KEPT_FOR_FACTORY : planResult }) as never)
  on('tool.call', { tool: 'Edit' }, () => ({ result: 'edited' }) as never)
  on('tool.call', { tool: 'Bash' }, () => ({ result: 'ran' }) as never)
  // The engine's question dialog: the next answer, or dismissed when none is left.
  const asked: string[] = []
  on('tool.call', { tool: 'AskUserQuestion' }, async (_, e) => {
    const q = (e as unknown as { questions: { question: string }[] }).questions[0]!.question
    asked.push(q)
    // The checks question has its own answer, so the other dialogs' answers stay in order.
    const isChecks = q.startsWith('Before the factory runs the checks')
    // `holdAsk`: the checks question stays open until the test releases it.
    if (isChecks && holdAsk) await held
    const a = isChecks ? (checksOk ?? undefined) : answers.shift()
    if (a === undefined) throw new Error('dismissed')
    return { result: { questions: (e as unknown as { questions: unknown }).questions, answers: { [q]: a } } } as never
  })
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
  return { limits, spawned, ran, sent, toasts, written, release, asked, clock, sends, registered, setConfig: (c: string) => void (configCommit = c) }
}

const texts = async (ui: { findAll: (q: { type: 'Text' }) => Promise<unknown[]> }) =>
  (await ui.findAll({ type: 'Text' })).map(t => String((t as { text?: string }).text ?? '')).join(' | ')

// An agent of the run answers: its turn completes, and the factory moves on.
async function answer($: Engine, id: string, text: string, reason: 'answer' | 'error' = 'answer') {
  await $.turn.complete({ answer: text, durationMs: 1000, isAborted: false, turnId: `t-${id}`, agentId: id, reason } as never)
  await settled()
}

async function step($: Engine, agentId: string) {
  const s = $.turn.step({ turnId: 't', index: 0, model: 'm', messageCount: 1, agentId } as never)
  for await (const _ of s) { /* drain */ }
  await s.result
}

async function startRun($: Engine) {
  await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
  const r = await $.command.run({ command: 'factory', args: 'Rate limiter' } as never)
  await settled()
  return String(r.text)
}

async function command($: Engine, args: string) {
  const r = await $.command.run({ command: 'factory', args } as never)
  await settled()
  return String(r.text)
}

// From the start to the reviews: spec a1, builder a2, reviewers a3 (security) and a4 (code).
async function toReviews($: Engine) {
  await startRun($)
  await answer($, 'a1', SPEC_ANSWER)
  // goal-run approves the plan: its dialog or pane passes it on.
  await command($, 'plan-approved')
  await answer($, 'a2', 'built')
}

// The transitions run after the event that caused them returns (in the plugin's own copy of the module).
async function settled() {
  for (let i = 0; i < 40; i++) await new Promise<void>(r => (globalThis as unknown as { setTimeout: (f: () => void, ms: number) => void }).setTimeout(r, 0))
}

const last = (w: { spawned: Spawned[] }) => w.spawned.at(-1)!

async function bandText($: Engine) {
  const band = await $.ui.mount({ ...BAND, surface: 'terminal' } as never)
  const t = await texts(band)
  await band.unmount()
  return t
}

describe('a run from the feature to the PR', () => {
  test('spec, the plan in goal-run, build, checks, both reviews, the approver, then your Open PR', async ($, on) => {
    const w = engine(on)
    const started = await startRun($)
    expect(started).toMatch(/Factory run started: Rate limiter\. Branch factory\/rate-limiter, worktree \/repo\/\.factory\/rate-limiter/)
    // The worktree is next to the repository, not in it: nothing in the main checkout scans it.
    expect(w.ran).toContain('git worktree add -b factory/rate-limiter /repo/.factory/rate-limiter abc123')
    expect(last(w)).toMatchObject({ subagentType: 'factory:spec-writer', description: 'factory · spec-writer', cwd: '/repo/.factory/rate-limiter' })
    expect(last(w).prompt).toContain('Rate limiter')

    // The spec's tasks go to goal-run's plan, through the main Claude.
    await step($, 'a1')
    await answer($, 'a1', SPEC_ANSWER)
    expect(w.sent.at(-1)).toContain(PLAN)
    expect(w.sent.at(-1)).toMatch(/source "factory"/)
    expect(w.sent.at(-1)).toContain('Middleware with Retry-After')
    expect(w.spawned).toHaveLength(1)

    // The person approves in goal-run's dialog: the builder starts.
    await $.tool.call({ tool: PLAN, goal: 'Rate limiter', source: 'factory', tasks: [{ title: 'Token bucket core', priority: 'high' }] } as never)
    await settled()
    expect(last(w)).toMatchObject({ id: 'a2', subagentType: 'factory:builder', description: 'factory · builder, round 1' })

    // Green checks, then the two reviewers at once, on what will be pushed.
    await answer($, 'a2', 'Done, committed.')
    expect(w.ran).toContain('npm test')
    expect(w.ran).toContain('git diff --stat abc123 HEAD')
    expect(w.spawned.slice(2).map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
    expect(w.spawned[2]!.prompt).toContain('src/mw.ts | 40')
    expect(w.spawned[2]!.prompt).toContain('git -C /repo/.factory/rate-limiter diff abc123..HEAD')

    await answer($, 'a3', PASS)
    expect(w.spawned).toHaveLength(4)
    await answer($, 'a4', PASS)
    expect(last(w)).toMatchObject({ id: 'a5', subagentType: 'factory:approver' })

    // The approver is an agent: its APPROVE readies the PR, and the person opens it.
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: spec met, tests green')
    const sentBefore = w.sent.length
    expect(w.toasts.at(-1)).toMatch(/Open PR/)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' } as never)
    expect(await texts(band)).toMatch(/approved: spec met, tests green/)
    await band.press({ key: 'f-pr' })
    await settled()
    await band.unmount()
    expect(w.sent.length).toBe(sentBefore + 1)
    expect(w.sent.at(-1)).toMatch(/Push branch factory\/rate-limiter/)
    expect(w.sent.at(-1)).toMatch(/spec met, tests green/)

    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    const text = await texts(pane)
    expect(text).toMatch(/✓ spec-writer \(sonnet\) · 3 tasks/)
    expect(text).toMatch(/✓ approver/)
    // Only requested: it reads as opened once Claude reports the PR's link.
    expect(text).toMatch(/PR requested \(Claude\)/)
    expect(text).not.toMatch(/✓ open PR/)
    expect(text).toMatch(/2k tokens/)
    await pane.unmount()
  })

  // Without the skeptic: what the builder gets back. (The skeptic's own tests are below.)
  test('changes send the builder back with the findings, and every reviewer looks again', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    expect(last(w)).toMatchObject({ id: 'a5', subagentType: 'factory:builder', description: 'factory · builder, round 2' })
    expect(last(w).prompt).toContain('Retry-After is in ms, not seconds')

    const pane = await $.ui.mount({ ...PANE, surface: 'desktop' } as never)
    expect(await texts(pane)).toMatch(/fixing 1 finding/)
    const svg = (await pane.findAll({ type: 'Svg' } as never))[0] as unknown as { props: { source: string } }
    expect(svg.props.source).toContain('builder · round 2')
    // The light theme set in /config: the light palette's background.
    expect(svg.props.source).toContain('#fbfaf7')
    await pane.unmount()

    // The fix is new code for security too.
    await answer($, 'a5', 'fixed')
    expect(w.spawned.slice(5).map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
    // A late answer from round 1's reviewer doesn't count for round 2.
    await answer($, 'a4', PASS)
    await answer($, 'a6', PASS)
    expect(w.spawned).toHaveLength(7)
    await answer($, 'a7', PASS)
    expect(last(w).subagentType).toBe('factory:approver')
  })

  // Without the skeptic: what the builder gets back. (The skeptic's own tests are below.)
  test('at the round limit the approver decides on what it has', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    await answer($, 'a5', 'fixed')
    await answer($, 'a6', PASS)
    await answer($, 'a7', CHANGES)
    expect(last(w).subagentType).toBe('factory:approver')
    expect(last(w).prompt).toContain('Retry-After')
  })

  test('work the builder left uncommitted is committed before the checks, without dependencies or credentials', async ($, on) => {
    const w = engine(on, { dirty: true })
    await toReviews($)
    const at = (c: string) => w.ran.indexOf(c)
    expect(at('git add -u')).toBeGreaterThan(-1)
    // Each new file on its own, a Hebrew name as it is: the .env inside the new app/ folder stays out.
    expect(w.ran).toContain('git add -- src/limit/new.ts src/limit/שלום.ts app/index.js')
    expect(w.ran.some(c => /add .*(node_modules|\.env|server\.key)/.test(c))).toBe(false)
    expect(w.ran).not.toContain('git add -A')
    expect(at('git commit -m factory: Rate limiter')).toBeGreaterThan(at('git add -- src/limit/new.ts src/limit/שלום.ts app/index.js'))
    expect(at('npm test')).toBeGreaterThan(at('git commit -m factory: Rate limiter'))
    expect(last(w).subagentType).toBe('factory:code-reviewer')
    // The person and the PR prompt hear what was left out.
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await texts(pane)).toMatch(/Left out of the commits: app\/\.env, node_modules\/, \.env, certs\/server\.key/)
    await pane.unmount()
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    expect(w.sent.at(-1)).toMatch(/left these new files out of its commits.*node_modules\//)
  })

  test('the worktree folder is kept out of git through the exclude file git names', async ($, on) => {
    const w = engine(on)
    await startRun($)
    expect(w.ran).toContain('git rev-parse --git-path info/exclude')
    expect(w.written['/repo/.git/info/exclude']).toBe('.factory/\n')
    await command($, 'stop')
    await command($, 'Second feature')
    expect(w.written['/repo/.git/info/exclude']).toBe('.factory/\n')
  })

  test("the review-only guard leaves a build run's builder alone: it adds and commits in its own worktree", async ($, on) => {
    engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    expect(await $.tool.call({ tool: 'Bash', agentId: 'a2', command: 'git add -A' } as never).then(r => JSON.stringify(r ?? {}))).not.toMatch(/changes nothing/)
  })

  test('a credential the builder staged itself is unstaged before the commit, and listed as left out', async ($, on) => {
    const w = engine(on, { dirty: true, stagedNew: ['config/.env', 'src/limit/new.ts'] })
    await toReviews($)
    const at = (c: string) => w.ran.indexOf(c)
    expect(at('git reset -q -- config/.env')).toBeGreaterThan(-1)
    expect(at('git commit -m factory: Rate limiter')).toBeGreaterThan(at('git reset -q -- config/.env'))
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await texts(pane)).toMatch(/Left out of the commits: .*config\/\.env/)
    await pane.unmount()
  })

  test('a credential the builder committed itself stops the run before the checks', async ($, on) => {
    const w = engine(on, { committedNew: ['src/mw.ts', 'certs/server.key'] })
    await toReviews($)
    expect(w.ran).not.toContain('npm test')
    expect(await bandText($)).toMatch(/committed files the factory never commits: certs\/server\.key/)
  })

  test('the history scan for committed credentials failing stops the run; it is not read as clean', async ($, on) => {
    const w = engine(on, { historyFails: true })
    await toReviews($)
    expect(w.ran).not.toContain('npm test')
    expect(await bandText($)).toMatch(/could not read the branch's history for files the factory never commits/)
  })

  test('history scan output git did not frame as asked (a signature line first) stops the run; it is not read as clean', async ($, on) => {
    const w = engine(on, { historyOut: `No signature\n\0${'a'.repeat(40)}\0\n.env\0` })
    await toReviews($)
    expect(w.ran).not.toContain('npm test')
    expect(await bandText($)).toMatch(/could not read the branch's history for files the factory never commits/)
  })

  test('a framed history scan with no never-commit file lets the run go on to the checks', async ($, on) => {
    const w = engine(on, { historyOut: `\0${'a'.repeat(40)}\0\nsrc/mw.ts\0src/limit.ts\0` })
    await toReviews($)
    expect(w.ran).toContain('npm test')
  })

  test("a commit that fails stops the run, for the person to look at", async ($, on) => {
    const w = engine(on, { dirty: true, commitFails: true })
    await toReviews($)
    expect(w.ran).not.toContain('npm test')
    expect(await bandText($)).toMatch(/could not be committed: Please tell me who you are/)
  })
})

describe('the worktree', () => {
  test('a taken name gets a number, counted from the feature', async ($, on) => {
    const w = engine(on, { worktree: ["fatal: a branch named 'factory/rate-limiter' already exists", "fatal: '/repo/.factory/rate-limiter-2' already exists"] })
    const started = await startRun($)
    expect(w.ran.filter(c => c.startsWith('git worktree add'))).toEqual([
      'git worktree add -b factory/rate-limiter /repo/.factory/rate-limiter abc123',
      'git worktree add -b factory/rate-limiter-2 /repo/.factory/rate-limiter-2 abc123',
      'git worktree add -b factory/rate-limiter-3 /repo/.factory/rate-limiter-3 abc123',
    ])
    expect(started).toMatch(/Branch factory\/rate-limiter-3/)
    expect(last(w).prompt).toContain('docs/specs/rate-limiter-3.md')
  })

  test('any other failure is reported at once', async ($, on) => {
    const w = engine(on, { worktree: ['fatal: not a valid object name: abc123'] })
    const started = await startRun($)
    expect(started).toMatch(/Could not create a worktree for the run: fatal: not a valid object name/)
    expect(w.ran.filter(c => c.startsWith('git worktree add'))).toHaveLength(1)
    expect(w.spawned).toHaveLength(0)
  })
})

describe('the checks come before any reviewer', () => {
  test('red checks go back to the builder, then to the person, who can retry them', async ($, on) => {
    const w = engine(on, { fails: 5 })
    await toReviews($)
    expect(last(w)).toMatchObject({ id: 'a3', subagentType: 'factory:builder' })
    expect(last(w).prompt).toContain('expected 429')
    await answer($, 'a3', 'fixed?')
    expect(w.spawned).toHaveLength(3)
    expect(w.spawned.some(s => s.subagentType.endsWith('reviewer'))).toBe(false)
    expect(await bandText($)).toMatch(/checks still fail after 2 builder passes: npm test/)

    // Not a PR: Approve isn't offered, and /factory approve says why.
    expect(await command($, 'approve')).toMatch(/^Nothing to approve: The checks still fail/)
    expect(w.sent.filter(t => /Push branch/.test(t))).toEqual([])
    const tests = w.ran.filter(c => c === 'npm test').length
    expect(await command($, 'retry')).toMatch(/Retrying: the checks/)
    expect(w.ran.filter(c => c === 'npm test').length).toBe(tests + 1)
  })

  test('no checks at all is a skip', async ($, on) => {
    const w = engine(on, { files: [] })
    await toReviews($)
    expect(w.ran.filter(c => !c.startsWith('git '))).toEqual([])
    expect(w.spawned.slice(2).map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
  })

  test('the checks option wins over detection, and autoPr opens the PR on APPROVE', { options: { checks: 'make test; make lint', autoPr: 'on' } }, async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(w.ran.filter(c => !c.startsWith('git '))).toEqual(['make test', 'make lint'])
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: good')
    expect(w.sent.at(-1)).toMatch(/Push branch factory\/rate-limiter/)
  })
})

describe('a fresh worktree gets its dependencies', () => {
  test("the lockfile's install runs once, before the first checks", async ($, on) => {
    const w = engine(on, { files: ['package.json', 'package-lock.json'] })
    await toReviews($)
    expect(w.ran.filter(c => !c.startsWith('git '))).toEqual(['npm ci', 'npm test'])
  })

  test('the setup option wins over the lockfile', { options: { setup: 'pnpm install' } }, async ($, on) => {
    const w = engine(on, { files: ['package.json', 'package-lock.json'] })
    await toReviews($)
    expect(w.ran.filter(c => !c.startsWith('git '))).toEqual(['pnpm install', 'npm test'])
  })

  test("a failed setup is the person's, not the builder's", async ($, on) => {
    const w = engine(on, { files: ['package.json', 'yarn.lock'], fails: 1 })
    await toReviews($)
    expect(w.ran.filter(c => !c.startsWith('git '))).toEqual(['yarn install --frozen-lockfile'])
    expect(w.spawned).toHaveLength(2)
    expect(await bandText($)).toMatch(/The setup failed: yarn install --frozen-lockfile/)
    await command($, 'retry')
    expect(w.ran.filter(c => !c.startsWith('git '))).toEqual(['yarn install --frozen-lockfile', 'yarn install --frozen-lockfile', 'npm test'])
    expect(last(w).subagentType).toBe('factory:code-reviewer')
  })
})

describe('the plan', () => {
  test("without goal-run, the factory asks for the plan's approval itself", async ($, on) => {
    const w = engine(on, { goalRun: false })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    expect(w.sent).toEqual([])
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' } as never)
    expect(await texts(band)).toMatch(/waiting for you to approve the plan/)
    await band.press({ key: 'f-approve-plan' })
    await settled()
    expect(last(w).subagentType).toBe('factory:builder')
    await band.unmount()
  })

  test("a regular plan's answers don't move the factory's", async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await $.classic.PostToolUse({ tool_name: PLAN, tool_input: {}, tool_response: 'Approved. Session goal: Ship it. 0/2 tasks done (0%).' } as never)
    await $.classic.PostToolUse({ tool_name: PLAN, tool_input: {}, tool_response: 'The person wants changes to the plan. Ask what to change, then propose it again with this tool.' } as never)
    await settled()
    expect(w.spawned).toHaveLength(1)
    expect(await bandText($)).toMatch(/waiting for you to approve the plan/)
  })

  test('with a goal of your own in goal-run, the factory asks in its band', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await $.classic.PostToolUse({ tool_name: PLAN, tool_input: {}, tool_response: PLAN_KEPT_FOR_FACTORY } as never)
    await settled()
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' } as never)
    expect(await texts(band)).toMatch(/goal-run keeps your own goal/)
    await band.press({ key: 'f-approve-plan' })
    await settled()
    await band.unmount()
    expect(last(w).subagentType).toBe('factory:builder')
  })

  test('changes to the plan go back to the spec-writer', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await $.classic.PostToolUse({ tool_name: PLAN, tool_input: {}, tool_response: planChangesForFactory('split the middleware task') } as never)
    await settled()
    expect(last(w)).toMatchObject({ id: 'a2', subagentType: 'factory:spec-writer' })
    expect(last(w).prompt).toContain('split the middleware task')
  })

  test("a role the engine wouldn't register runs as a general-purpose agent with the role's instructions", async ($, on) => {
    const w = engine(on, { denyType: true })
    await startRun($)
    expect(last(w).subagentType).toBe('general-purpose')
    expect(last(w).prompt).toMatch(/spec-writer/)
    expect(last(w).prompt).toContain('Rate limiter')
  })
})

describe('the person decides', () => {
  test("a spec with no tasks can't be approved into a PR; Retry asks the spec-writer again", async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', 'I wrote a spec.')
    expect(await bandText($)).toMatch(/The spec-writer gave no TASKS list/)
    expect(await command($, 'approve')).toMatch(/^Nothing to approve/)
    expect(w.sent).toEqual([])
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' } as never)
    await band.press({ key: 'f-retry' })
    await settled()
    await band.unmount()
    expect(last(w)).toMatchObject({ id: 'a2', subagentType: 'factory:spec-writer' })
  })

  test('an ESCALATE waits for the person; Approve PR sends the PR prompt', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: ESCALATE\nREASON: the spec asks for Redis, the build uses memory')
    expect(w.toasts.at(-1)).toMatch(/The factory needs you/)
    const before = w.sent.length
    expect(await bandText($)).toMatch(/the spec asks for Redis/)
    expect(await command($, 'retry')).toMatch(/The approver escalated/)

    expect(await command($, 'approve')).toMatch(/Claude opens the PR/)
    expect(w.sent.length).toBe(before + 1)
    expect(w.sent.at(-1)).toMatch(/factory\/rate-limiter/)
  })

  test("stop ends the run: its agents' tool calls are refused, late answers ignored, the band goes", async ($, on) => {
    const w = engine(on)
    await startRun($)
    expect(await command($, 'stop')).toMatch(/Stopped\. The branch factory\/rate-limiter/)
    const edit = { tool: 'Edit', file_path: '/repo/.factory/rate-limiter/a.ts', old_string: 'a', new_string: 'b' }
    expect(String((await $.tool.call({ ...edit, agentId: 'a1' } as never)).deny)).toMatch(/factory run was stopped/)
    expect((await $.tool.call(edit as never)).result).toBe('edited')
    expect((await $.tool.call({ ...edit, agentId: 'other' } as never)).result).toBe('edited')
    await answer($, 'a1', SPEC_ANSWER)
    expect(w.sent).toEqual([])
    expect(await bandText($)).not.toMatch(/🏭/)
  })

  test('a check that runs long shows which one, its place and its time, in the band and the pane', async ($, on) => {
    const w = engine(on, { hold: 'npm run lint', pkg: '{"scripts":{"test":"x","lint":"y","typecheck":"z"}}' })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    expect(w.ran.at(-1)).toBe('npm run lint')
    expect(await bandText($)).toMatch(/checks 2\/3 · npm run lint · 0:00/)
    await w.clock.advance(65_000)
    expect(await bandText($)).toMatch(/checks 2\/3 · npm run lint · 1:0\d/)
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await texts(pane)).toMatch(/checks 2\/3 · npm run lint · 1:0\d/)
    expect(await texts(pane)).toMatch(/2\/3 npm run lint/)
    await pane.unmount()
    w.release()
    await settled()
    expect(await bandText($)).not.toMatch(/checks \d\/\d/)
  })

  test('while the question before the checks is open, the run reads as waiting for you', async ($, on) => {
    const w = engine(on, { holdAsk: true })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    expect(w.asked.at(-1)).toMatch(/^Before the factory runs the checks/)
    expect(await bandText($)).toMatch(/waiting for your OK to run the checks/)
    expect(w.ran.filter(c => c.startsWith('npm'))).toEqual([])
    w.release()
    await settled()
    expect(await bandText($)).not.toMatch(/waiting for your OK/)
    expect(w.ran).toContain('npm test')
  })

  test('a Stop during the checks ends them: the commands left are not run', async ($, on) => {
    const w = engine(on, { hold: 'npm test', pkg: '{"scripts":{"test":"x","lint":"y","typecheck":"z"}}' })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    // goal-run approves the plan: its dialog or pane passes it on.
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    expect(w.ran.at(-1)).toBe('npm test')
    await command($, 'stop')
    w.release()
    await settled()
    expect(w.ran.filter(c => c.startsWith('npm'))).toEqual(['npm test'])
    expect(w.spawned.some(s => s.subagentType.endsWith('reviewer'))).toBe(false)
  })

  test('a Stop while the reviews are being routed holds: no reviewer starts, the run stays stopped', async ($, on) => {
    // startReviews awaits the route's git diff before it moves the run to review (2026-11-13 inspection).
    const w = engine(on, { hold: 'git diff --name-status -z *' })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await settled()
    expect(w.ran.some(c => c.startsWith('git diff --name-status -z '))).toBe(true)
    expect(await command($, 'stop')).toMatch(/^Stopped/)
    w.release()
    await settled()
    expect(w.spawned.some(s => s.subagentType.endsWith('reviewer'))).toBe(false)
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toMatch(/Phase: stopped/)
  })

  test("a stopped run's agents stay refused after a new run starts", async ($, on) => {
    engine(on)
    await startRun($)
    await command($, 'stop')
    await command($, 'Second feature')
    const edit = { tool: 'Edit', file_path: '/repo/.factory/rate-limiter/a.ts', old_string: 'a', new_string: 'b' }
    expect(String((await $.tool.call({ ...edit, agentId: 'a1' } as never)).deny)).toMatch(/factory run was stopped/)
    expect((await $.tool.call({ ...edit, agentId: 'a2' } as never)).result).toBe('edited')
  })

  test('a run from a to-do item has Claude mark the item done once the PR is open', async ($, on) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const started = await command($, factoryArgs('Rate limiter — bursts must pass', 'k3x-1a2b3'))
    expect(started).toMatch(/Factory run started: Rate limiter — bursts must pass\./)
    expect(last(w).prompt).not.toContain('followup:')
    await answer($, 'a1', SPEC_ANSWER)
    // goal-run approves the plan: its dialog or pane passes it on.
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    expect(w.sent.at(-1)).toMatch(/call mcp__followups__done with id "k3x-1a2b3"/)
  })

  test('a second run waits for the first', async ($, on) => {
    engine(on)
    await startRun($)
    expect(await command($, 'Something else')).toMatch(/already going: Rate limiter/)
  })

  test('the roles are hidden from the model', async ($, on) => {
    engine(on)
    on('agent.offer', () => ({ isOffered: true }) as never)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    expect((await $.agent.offer({ agent: 'factory:builder', description: 'x', source: 'plugin' } as never)).isOffered).toBe(false)
    expect((await $.agent.offer({ agent: 'Explore', description: 'x', source: 'built-in' } as never)).isOffered).toBe(true)
  })
})

describe('goals and to-do items reach the factory only when the person picks it', () => {
  const START = (lines: string[]) => [lines.length === 1 ? 'Start this item from my to-do list:' : `Start these ${lines.length} items from my to-do list, one after the other:`, ...lines, 'Do the work. When an item is finished, call mcp__followups__done with its id (and a short note).'].join('\n')

  test("goal-run's goal prompt and a to-do item's Start go on as they were: no run starts by itself", { options: { takeOver: 'on' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const goal = goalPrompt('Rate limiter for the API')
    expect(String((await $.prompt.submit({ text: goal, origin: { kind: 'plugin', name: 'goal-run' } } as never)).text)).toBe(goal)
    const one = START([startLine({ id: 'k3x-1a2b3', title: 'Add a rate limiter', kind: 'bug' })])
    expect(String((await $.prompt.submit({ text: one, origin: { kind: 'plugin', name: 'followups' } } as never)).text)).toBe(one)
    await settled()
    expect(w.spawned).toHaveLength(0)
  })

  test("a to-do item sent with followups' 🏭 (/factory with its id) is marked done once the PR is open", async ($, on) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    expect(await command($, factoryArgs('Add a rate limiter — bursts must pass (src/mw.ts)', 'k3x-1a2b3'))).toMatch(/^Factory run started/)
    expect(last(w).prompt).toContain('Feature: Add a rate limiter — bursts must pass (src/mw.ts)')
    await answer($, 'a1', SPEC_ANSWER)
    // goal-run approves the plan: its dialog or pane passes it on.
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    expect(w.sent.at(-1)).toMatch(/mcp__followups__done with id "k3x-1a2b3"/)
  })

  test("a paste's wrapper doesn't reach the feature, the branch or the spec file", async ($, on) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const r = await command($, '<pasted_content id="e2b6">\nFix the retry bug in the router\n</pasted_content id="e2b6">')
    expect(r).toMatch(/Factory run started: Fix the retry bug in the router\. Branch factory\/fix-the-retry-bug-in-the-router/)
    expect(last(w).prompt).toContain('docs/specs/fix-the-retry-bug-in-the-router.md')
    expect(last(w).prompt).not.toContain('pasted_content')
  })
})

describe('an agent that fails says why', () => {
  test('an API error retries once on the session model, then stops with the reason', async ($, on) => {
    const w = engine(on)
    await startRun($)
    expect(last(w).model).toBe('sonnet')
    await answer($, 'a1', 'model not available: sonnet', 'error')
    expect(last(w)).toMatchObject({ id: 'a2', subagentType: 'factory:spec-writer' })
    expect(last(w).model).toBeUndefined()
    await answer($, 'a2', 'overloaded', 'error')
    expect(w.spawned).toHaveLength(2)
    expect(await bandText($)).toMatch(/The spec-writer stopped: an API error ended it: overloaded/)
    // The diagram doesn't call the plan approved.
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    const t = await texts(pane)
    expect(t).toMatch(/◌ plan approval/)
    expect(t).toMatch(/✕ spec-writer/)
    await pane.unmount()
  })

  test('a refusal is reported with the explanation, not retried', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await $.turn.complete({ answer: '', durationMs: 10, isAborted: false, turnId: 't', agentId: 'a1', reason: 'refusal', refusal: { category: 'x', explanation: 'policy' } } as never)
    await settled()
    expect(w.spawned).toHaveLength(1)
    expect(await bandText($)).toMatch(/The spec-writer stopped: the model refused: policy/)
  })
})

describe("a plan goal-run approves isn't approved past it", () => {
  test("with goal-run as the gate, the pane has no Approve plan and /factory approve points to goal-run", async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await pane.find({ key: 'p-approve-plan' } as never)).toBeFalsy()
    expect(await texts(pane)).toMatch(/waits for your approval in goal-run/)
    await pane.unmount()
    expect(await command($, 'approve')).toMatch(/waits for your approval in goal-run/)
    expect(w.spawned.filter(a => a.subagentType === 'factory:builder')).toHaveLength(0)
    await command($, 'plan-approved')
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder' })
  })

  test('without goal-run the factory approves its own plan, in its band and pane', async ($, on) => {
    const w = engine(on, { goalRun: false, answers: [''] })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await pane.find({ key: 'p-approve-plan' } as never)).toBeTruthy()
    await pane.unmount()
    expect(await command($, 'approve')).toBe('Plan approved: the builder starts.')
    await settled()
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder' })
  })
})

describe('a run that seems stuck says where it is', () => {
  const toBuild = async ($: Engine) => {
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
  }

  // A 2-minute limit keeps the clock's frame ticks few: 10 minutes of them made this test slow on some
  // machines (code review 2, F2).
  test('a check that runs out of time stops the run for the person: the builder is not sent to fix it', { options: { checkTimeout: '2' } } as never, async ($: Engine, on: On) => {
    // npm test runs to the limit and fails there: killed at the timeout.
    const w = engine(on, { hold: 'npm test', fails: 1 })
    await toBuild($)
    await answer($, 'a2', 'built')
    expect(w.limits['npm test']).toBe(120_000)
    await w.clock.advance(120_000)
    w.release()
    await settled()
    expect(w.spawned.filter(a => a.subagentType === 'factory:builder')).toHaveLength(1)
    expect(await bandText($)).toMatch(/npm test didn't finish in 2:00\. It may be slow or hung/)
    expect(Object.entries(w.written).find(([k]) => /checks\.md$/.test(k))?.[1]).toMatch(/⏱ \(timed out after 2:00\) npm test/)
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toMatch(/TIMED OUT: npm test/)
  })

  test('a question nobody answers holds no later session: a new run starts after session.start (code review 2, F2)', async ($, on) => {
    const w = engine(on, { holdAsk: true })
    await toBuild($)
    await answer($, 'a2', 'built')
    expect(w.asked.at(-1)).toMatch(/^Before the factory runs the checks/)
    // The question stays open; the session restarts and the run is stopped, then a new one starts.
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await command($, 'stop')
    await command($, 'Add a cache')
    await settled()
    expect(last(w)).toMatchObject({ subagentType: 'factory:spec-writer' })
    expect(last(w).prompt).toContain('Feature: Add a cache')
  })

  test('the checkTimeout option shortens the limit; Claude Code allows 10 minutes at most', { options: { checkTimeout: '5' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await toBuild($)
    await answer($, 'a2', 'built')
    await settled()
    await w.clock.advance(10)
    await settled()
    expect(w.limits['npm test']).toBe(300_000)
  })

  test('a refusal that names timeoutMs is no timeout', () => {
    expect(couldNotStart('init.timeoutMs is a whole number of ms, 1 to 600000')).toBe(true)
    expect(couldNotStart('Command timed out after 600000 ms')).toBe(false)
  })

  test("a builder that replaced the branch's history: the person says which branch it is on, and everything compares with it", async ($, on) => {
    const w = engine(on, { baseGone: true, branch: 'main', answers: ['origin/pr-106'] })
    await toBuild($)
    await answer($, 'a2', 'built')
    await settled()
    expect(w.asked.find(q => /no longer starts from main/.test(q))).toBeTruthy()
    expect(w.ran).toContain('git diff --stat def456 HEAD')
    expect(w.ran).not.toContain('git diff --stat abc123 HEAD')
    expect(w.spawned.find(a => a.subagentType === 'factory:security-reviewer')?.prompt).toContain('since def456')
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    expect(w.sent.at(-1)).toMatch(/open a pull request from it into pr-106 \(the branch it is built on/)
  })

  test("unanswered, the run waits; /factory base <branch> moves it and the run goes on", async ($, on) => {
    const w = engine(on, { baseGone: true, answers: ['Not now'] })
    await toBuild($)
    await answer($, 'a2', 'built')
    await settled()
    expect(await bandText($)).toMatch(/no longer starts from abc123/)
    expect(await command($, 'base nope')).toMatch(/No branch or commit "nope"/)
    expect(await command($, 'base origin/pr-106')).toMatch(/now based on origin\/pr-106/)
    await settled()
    expect(w.spawned.find(a => a.subagentType === 'factory:security-reviewer')?.prompt).toContain('since def456')
  })

  test("the PR goes into the branch the run started from", async ($, on) => {
    const w = engine(on, { branch: 'feature/router' })
    await toBuild($)
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    expect(w.sent.at(-1)).toMatch(/into feature\/router/)
  })

  test("the band has a progress bar and the agent's last action; a quiet agent shows in orange how long", async ($, on) => {
    const w = engine(on)
    await toBuild($)
    await $.tool.call({ tool: 'Edit', file_path: '/repo/.factory/rate-limiter/src/mw.ts', old_string: 'a', new_string: 'b', agentId: 'a2' } as never)
    let t = await bandText($)
    expect(t).toMatch(/▰+▱+ \d+%/)
    expect(t).toMatch(/building · editing mw\.ts · 0:00 ago/)
    await w.clock.advance(6 * 60_000 + 1_000)
    t = await bandText($)
    expect(t).toMatch(/building · no activity for 6:0\d/)
    const status = String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)
    expect(status).toMatch(/^Factory run: Rate limiter/)
    expect(status).toMatch(/Phase: build · \d+% · building · no activity/)
    expect(status).toMatch(/Last agent action: builder editing mw\.ts, 6:0\d ago \(1 tool calls this step\)/)
    expect(await command($, 'status')).toBe(status)
  })

  test('the progress only grows through a run that passes', async ($, on) => {
    const w = engine(on)
    const seen: number[] = []
    const pct = async () => seen.push(Number(/(\d+)%/.exec(await bandText($))?.[1]))
    await startRun($)
    await pct()
    await answer($, 'a1', SPEC_ANSWER)
    await pct()
    await command($, 'plan-approved')
    await pct()
    await answer($, 'a2', 'built')
    await pct()
    await answer($, 'a3', PASS)
    await pct()
    await answer($, 'a4', PASS)
    await pct()
    expect(seen).toEqual([...seen].sort((a, b) => a - b))
    expect(seen.at(-1)).toBeGreaterThanOrEqual(85)
    void w
  })
})

describe('reviewers by the diff, a guard on what agents run, and a skeptic', () => {
  test('the route reads the files and lines a diff changed, and only ever adds review', () => {
    expect(routeReview([{ path: 'src/mw.ts', status: 'M' }], ['const x = 1'])).toEqual({ deep: false, focus: [] })
    const agentFile = routeReview([{ path: 'plugins/x/CLAUDE.md', status: 'M' }], [])
    expect(agentFile.deep).toBe(true)
    expect(agentFile.focus[0]).toMatch(/prompt injection/)
    const deps = routeReview([{ path: 'package.json', status: 'M' }], [])
    expect([deps.deep, deps.focus.length]).toEqual([false, 1])
    expect(routeReview([{ path: 'db/migrations/0042_users.sql', status: 'A' }], []).deep).toBe(true)
    expect(routeReview([{ path: 'src/limit.ts', status: 'M' }], ['  if (!user.isAdmin) throw new Error()']).focus.join(' ')).toMatch(/Authentication/)
    expect(routeReview([{ path: 'tests/test_limit.py', status: 'D' }], []).focus.join(' ')).toMatch(/Tests were deleted/)
    expect(routeReview([{ path: 'tests/__snapshots__/a.snap', status: 'M' }], []).focus.join(' ')).toMatch(/Expected test output changed/)
    expect(routeReview([{ path: '.github/workflows/ci.yml', status: 'M' }], []).deep).toBe(true)
    const unread = routeReview([], [], false)
    expect([unread.deep, unread.focus[0]]).toEqual([true, expect.stringMatching(/couldn't read the whole diff/)])
    expect(changedOf('M\0src/a.ts\0R100\0old.ts\0new.ts\0D\0gone.ts\0')).toEqual([{ status: 'M', path: 'src/a.ts' }, { status: 'R100', path: 'new.ts' }, { status: 'D', path: 'gone.ts' }])
    expect(diffLines('diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new')).toEqual(['old', 'new'])
  })

  test("pushing, publishing, deploying or deleting outside the worktree is refused; quoted text isn't a command", () => {
    for (const c of ['git push origin factory/x', 'cd sub && git push', 'FOO=1 git push', 'git -C /w push', 'gh pr create --fill', 'npm publish', 'docker push img', 'terraform apply', 'kubectl apply -f x.yaml', 'vercel deploy --prod', 'rm -rf /', 'rm -rf ../other', 'rm -rf ~/x', 'git remote set-url origin x']) {
      expect([c, forbiddenCommand(c) !== '']).toEqual([c, true])
    }
    for (const c of ['npm test', 'git commit -m "never git push here"', 'rm -rf node_modules dist', 'git status', 'gh --version', 'git fetch origin', 'echo "npm publish"']) {
      expect([c, forbiddenCommand(c)]).toEqual([c, ''])
    }
  })

  test("in a review of the person's checkout, a command that changes it is refused; reading and /tmp are not", () => {
    for (const c of [
      'git stash', 'git stash -u', 'git checkout -- .', 'git -C /repo restore src/a.ts', 'git reset --hard', 'git clean -fd', 'git add -A',
      'git commit -m x', 'git switch main', 'git branch -D old', 'cd /repo && git stash', 'bash -c "git checkout ."',
      "sed -i 's/a/b/' src/a.ts", 'perl -pi -e s/a/b/ x', 'npm install', 'pnpm add lodash', 'rm src/a.ts', 'rm -rf build',
      'mv a.ts b.ts', 'cp /tmp/x src/a.ts', 'touch src/new.ts', 'echo x > src/a.ts', 'cat a >> notes.md', 'echo x | tee src/a.ts',
      'bash -c "echo x > src/a.ts"', 'dd if=/dev/zero of=src/a.bin', 'truncate -s 0 src/a.ts', 'git push',
      // a .. segment climbs out of /tmp (2026-11-13 inspection, reproduced)
      'echo x > /tmp/../src/a.ts', 'cp a /tmp/../src/a.ts', 'rm /tmp/../src/a.ts', 'dd if=/dev/zero of=/tmp/x/../../src/a.bin',
      'tee /tmp/../../repo/src/a.ts',
    ]) {
      expect([c, forbiddenInReview(c) !== '']).toEqual([c, true])
    }
    for (const c of [
      'git diff', 'git status --porcelain', 'git log --oneline -5', 'git show HEAD:src/a.ts', 'git branch --list', 'git blame src/a.ts',
      'npm test', 'python -m pytest -q', 'grep -rn "x > y" src', 'cat src/a.ts 2>/dev/null', 'npm test 2>&1', 'node a.js >/dev/null',
      'echo probe > /tmp/p.py', 'cp src/a.ts /tmp/a.ts', 'mkdir /tmp/probe', 'rm /tmp/probe/p.py', "sed -n '1,5p' src/a.ts", 'tee /tmp/out.txt',
      'git commit-graph verify', 'echo "git stash"',
    ]) {
      expect([c, forbiddenInReview(c)]).toEqual([c, ''])
    }
  })

  test('wrappers, paths, subshells, git options and a shell\'s -c string are seen through (code review 2, F1)', () => {
    for (const c of [
      'git -c foo=bar push', 'git --no-pager push', '/usr/bin/git push', 'env git push', 'env -i HOME=/x git push',
      'bash -c "git push"', "sh -c 'git push'", 'eval git push', 'eval "git push origin x"', '(git push)', 'echo $(git push)',
      'echo `git push`', 'xargs git push', 'time git push', 'nohup git push', 'npx vercel deploy', 'npx -y vercel deploy --prod',
      'pnpm dlx netlify deploy', 'npm exec -- wrangler deploy', 'timeout 30 git push', 'git --git-dir=/r/.git --work-tree /w push',
      'powershell -Command "git push"', 'C:\\Program` Files\\Git\\bin\\git.exe push',
    ]) {
      expect([c, forbiddenCommand(c) !== '']).toEqual([c, true])
    }
    for (const c of ['bash -c "npm test"', 'git -c core.pager=cat log', 'npx vitest run', 'xargs rm -f a.tmp', 'time npm run build']) {
      expect([c, forbiddenCommand(c)]).toEqual([c, ''])
    }
  })

  test('MCP tools that change a remote are refused to the run\'s agents; reading ones are not', () => {
    for (const t of ['mcp__github__push_files', 'mcp__github__create_or_update_file', 'mcp__github__create_pull_request', 'mcp__github__merge_pull_request', 'mcp__github__create_branch', 'mcp__github__delete_file', 'mcp__vercel__deploy']) {
      expect([t, forbiddenTool(t) !== '']).toEqual([t, true])
    }
    for (const t of ['mcp__github__get_file_contents', 'mcp__github__pull_request_read', 'mcp__github__list_branches', 'Read', 'Bash']) {
      expect([t, forbiddenTool(t)]).toEqual([t, ''])
    }
  })

  test("a run's agent is refused a git push; the main conversation isn't", async ($, on) => {
    on('tool.call', { tool: 'Bash' }, () => ({ result: 'ran' }) as never)
    engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    const denied = await $.tool.call({ tool: 'Bash', command: 'git push -u origin factory/rate-limiter', agentId: 'a2' } as never)
    expect(String((denied as { deny?: string }).deny)).toMatch(/don't do this \(git push\).*the person opens the PR/)
    const tests = await $.tool.call({ tool: 'Bash', command: 'npm test', agentId: 'a2' } as never)
    expect((tests as { deny?: string }).deny).toBeFalsy()
    const main = await $.tool.call({ tool: 'Bash', command: 'git push -u origin factory/rate-limiter' } as never)
    expect((main as { deny?: string }).deny).toBeFalsy()
    const pwsh = await $.tool.call({ tool: 'PowerShell', command: 'git push origin HEAD', agentId: 'a2' } as never)
    expect(String((pwsh as { deny?: string }).deny)).toMatch(/git push/)
    const mcp = await $.tool.call({ tool: 'mcp__github__create_pull_request', title: 'x', agentId: 'a2' } as never)
    expect(String((mcp as { deny?: string }).deny)).toMatch(/through an MCP tool/)
  })

  test("a diff that changes an agent's instructions: both reviewers are told to look, and the code reviewer runs on opus", async ($, on) => {
    const w = engine(on, { changedFiles: 'M\0CLAUDE.md\0M\0src/mw.ts\0' })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    const code = w.spawned.find(a => a.subagentType === 'factory:code-reviewer')!
    const security = w.spawned.find(a => a.subagentType === 'factory:security-reviewer')!
    expect(code.model).toBe('opus')
    for (const a of [code, security]) expect(a.prompt).toMatch(/What this diff calls for[\s\S]*prompt injection/)
  })

  test('a bare STANDS line does not swallow the ruling on the next line', () => {
    const f = [{ severity: 'major' as const, where: 'a.ts:1', text: 'x' }, { severity: 'major' as const, where: 'b.ts:2', text: 'y' }]
    const { kept, dropped } = applyRulings(f, 'F1: STANDS\nF2: REFUTED b.ts:2 the store is shared', () => false)
    expect(kept).toEqual([f[0]])
    expect(dropped).toEqual([{ finding: f[1], ruling: 'refuted', why: 'b.ts:2 the store is shared' }])
  })

  test('the rulings: refuted needs evidence, a security blocker always stands, downgraded is minor, unruled stands', () => {
    const f = [
      { severity: 'major' as const, where: 'a.ts:1', text: 'x' },
      { severity: 'blocker' as const, where: 'b.ts:2', text: 'y' },
      { severity: 'major' as const, where: 'c.ts:3', text: 'z' },
      { severity: 'major' as const, where: 'd.ts:4', text: 'w' },
    ]
    const { kept, dropped } = applyRulings(f, 'F1: REFUTED a.ts:1 already checks it\nF2: REFUTED nope\nF3: DOWNGRADED only a log line, c.ts:3\nF4: REFUTED', x => x === f[1])
    expect(kept).toEqual([f[1], { ...f[2], severity: 'minor' }, f[3]])
    expect(dropped.map(d => d.ruling)).toEqual(['refuted', 'downgraded'])
  })

  test('changes asked for: a skeptic checks the findings first; refuted, the approver decides and is told why', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    expect(last(w)).toMatchObject({ id: 'a5', subagentType: 'factory:skeptic', model: 'sonnet' })
    expect(last(w).prompt).toContain('F1. code [major] src/mw.ts:12 Retry-After is in ms, not seconds')
    expect(await bandText($)).toMatch(/a skeptic checks 1 finding/)
    await answer($, 'a5', 'Read mw.ts.\nF1: REFUTED src/mw.ts:12 divides by 1000 before it sets the header')
    expect(last(w)).toMatchObject({ id: 'a6', subagentType: 'factory:approver' })
    expect(last(w).prompt).toMatch(/the skeptic set aside with evidence[\s\S]*Retry-After is in ms, not seconds: refuted, src\/mw\.ts:12 divides by 1000/)
    expect(Object.entries(w.written).find(([k]) => /skeptic-rulings\.md$/.test(k))?.[1]).toMatch(/REFUTED: \[major\] src\/mw\.ts:12/)
    expect(w.spawned.filter(a => a.subagentType === 'factory:builder')).toHaveLength(1)
  })

  test('a finding that stands goes to the builder; a skeptic that fails refutes nothing', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    await answer($, 'a5', 'F1: STANDS')
    expect(w.sends.at(-1)?.text ?? last(w).prompt).toContain('Retry-After is in ms, not seconds')
  })

  test('two findings alike from one reviewer each take their own ruling, not the first one\'s', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', `${CHANGES}\n- [major] src/mw.ts:12 Retry-After is in ms, not seconds`)
    const prompt = last(w).prompt
    expect(prompt).toContain('F1. code [major] src/mw.ts:12 Retry-After is in ms, not seconds')
    expect(prompt).toContain('F2. code [major] src/mw.ts:12 Retry-After is in ms, not seconds')
    await answer($, 'a5', 'F1: STANDS the unit is wrong at src/mw.ts:12\nF2: REFUTED the header is already in seconds, src/mw.ts:12')
    // One stands, one refuted: the builder gets exactly one of the two, not both and not none.
    const toBuilder = w.sends.at(-1)?.text ?? last(w).prompt
    expect(toBuilder.match(/Retry-After is in ms, not seconds/g)).toHaveLength(1)
    expect(w.spawned.filter(a => a.subagentType === 'factory:builder')).toHaveLength(2)
  })

  test('with the skeptic option off, the findings go straight to the builder', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    expect(w.spawned.some(a => a.subagentType === 'factory:skeptic')).toBe(false)
  })

  test("a skeptic that can't start sends the findings to the builder as they are", async ($, on) => {
    const w = engine(on, { holdSkeptic: true })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    w.release()
    await settled()
    expect(w.sends.at(-1)?.text ?? last(w).prompt).toContain('Retry-After is in ms, not seconds')
    expect(await bandText($)).not.toMatch(/stopped/)
  })

  test("a Stop while the skeptic is starting holds, even when the skeptic then fails to start", async ($, on) => {
    const w = engine(on, { holdSkeptic: true })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    const sendsBefore = w.sends.length
    const builders = () => w.spawned.filter(a => a.subagentType === 'factory:builder').length
    const before = builders()
    expect(await command($, 'stop')).toMatch(/^Stopped/)
    w.release()
    await settled()
    // The failed start used to put the run back in review and send the findings to a builder.
    expect(builders()).toBe(before)
    expect(w.sends.length).toBe(sendsBefore)
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toMatch(/Phase: stopped/)
  })
})

describe('extra reviewers the main Claude adds, and steering a run', () => {
  const START = 'mcp__factory__start'
  const CONTROL = 'mcp__factory__control'
  const toReview = async ($: Engine, reviewers?: unknown) => {
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const r = await $.tool.call({ tool: START, feature: 'Rate limiter', ...(reviewers ? { reviewers } : {}) } as never)
    await settled()
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    return String(r.result)
  }

  test('a lens by name, one of its own with an agent; unknown, core, duplicate and past three are left out', () => {
    const { extras, ignored } = extrasFrom(['frontend', { name: 'A11y', focus: 'screen readers', agent: 'my-ux' }, 'nope', 'security', 'frontend', 'finops', 'deploy'])
    expect(extras).toEqual([{ name: 'frontend', focus: LENSES.frontend }, { name: 'a11y', focus: 'screen readers', agent: 'my-ux' }, { name: 'finops', focus: LENSES.finops }])
    expect(ignored).toEqual(['nope', 'security', 'frontend', 'deploy'])
  })

  test('the extras review beside security and code, each through its lens; all are waited for', async ($, on) => {
    const w = engine(on)
    const said = await toReview($, ['frontend', { name: 'a11y', focus: 'screen readers and focus order', agent: 'my-ux' }])
    expect(said).toMatch(/Extra reviewers: frontend, a11y\./)
    const types = w.spawned.slice(2).map(a => a.subagentType)
    expect(types).toEqual(['factory:security-reviewer', 'factory:code-reviewer', 'factory:reviewer', 'my-ux'])
    const front = w.spawned.find(a => a.subagentType === 'factory:reviewer')!
    expect(front).toMatchObject({ description: 'factory · frontend review', model: 'sonnet' })
    expect(front.prompt).toContain(`You are the frontend reviewer: look at ${LENSES.frontend}`)
    const own = w.spawned.find(a => a.subagentType === 'my-ux')!
    expect(own.model).toBeUndefined()
    expect(own.prompt).toContain('screen readers and focus order')
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', PASS)
    expect(w.spawned.some(a => a.subagentType === 'factory:approver')).toBe(false)
    await answer($, 'a6', PASS)
    expect(last(w)).toMatchObject({ subagentType: 'factory:approver' })
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    const t = await texts(pane)
    expect(t).toMatch(/frontend \(sonnet\)/)
    expect(t).toMatch(/a11y \(its own\)/)
    await pane.unmount()
  })

  test("without reviewers asked for, a run has security and code only", async ($, on) => {
    const w = engine(on)
    await toReview($)
    expect(w.spawned.slice(2).map(a => a.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
  })

  test('an extra that asks for changes sends the builder back like any reviewer', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on, { delivers: true })
    await toReview($, ['finops'])
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'VERDICT: CHANGES\nFINDINGS:\n- [major] infra/db.tf:3 a db.r6g.4xlarge for a cron job')
    expect(w.sends.at(-1)?.text).toContain('db.r6g.4xlarge')
  })

  test('the main Claude skips a check that hangs: the run goes on, and says it didn\'t run', async ($, on) => {
    const w = engine(on, { hold: 'npm test' })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    expect(w.ran.at(-1)).toBe('npm test')
    const r = await $.tool.call({ tool: CONTROL, action: 'skip-check', reason: 'hung on a prompt' } as never)
    expect(String(r.result)).toMatch(/^Skipped npm test: the run goes on/)
    await settled()
    expect(last(w)).toMatchObject({ subagentType: 'factory:code-reviewer' })
    expect(Object.entries(w.written).find(([k]) => /checks\.md$/.test(k))?.[1]).toMatch(/– \(skipped by the person\) npm test/)
    expect(w.spawned.find(a => a.subagentType === 'factory:security-reviewer')?.prompt).toMatch(/No checks ran|Skipped by the person/)
    w.release()
    await settled()
    expect(String((await $.tool.call({ tool: CONTROL, action: 'skip-check' } as never)).result)).toBe('No check is running to skip.')
  })

  test('a stuck builder is abandoned: its calls are refused, and Retry starts a new one', async ($, on) => {
    const w = engine(on, { delivers: true })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    const r = await $.tool.call({ tool: CONTROL, action: 'abandon-agent', reason: 'no activity for 20 minutes' } as never)
    expect(String(r.result)).toMatch(/^Abandoned the builder, round 1 \(no activity for 20 minutes\)/)
    expect(await bandText($)).toMatch(/Abandoned the builder/)
    const denied = await $.tool.call({ tool: 'Edit', file_path: '/w/a.ts', old_string: 'a', new_string: 'b', agentId: 'a2' } as never)
    expect((denied as { deny?: string }).deny).toBeTruthy()
    await command($, 'retry')
    await settled()
    expect(w.spawned.filter(a => a.subagentType === 'factory:builder').map(a => a.id)).toEqual(['a2', 'a3'])
  })

  test('reviewers added mid-run review from the next round; the sub-agents can\'t steer the run', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    const added = await $.tool.call({ tool: CONTROL, action: 'add-reviewers', reviewers: ['deploy'] } as never)
    expect(String(added.result)).toMatch(/^Added deploy/)
    expect((await $.tool.call({ tool: CONTROL, action: 'stop', agentId: 'a1' } as never) as { deny?: string }).deny).toMatch(/Only the main conversation/)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    expect(w.spawned.slice(2).map(a => a.description)).toEqual(['factory · security review', 'factory · code review', 'factory · deploy review'])
  })
})

describe('pytest that found nothing, or no pytest at all, is not a failure (code review 2, F3)', () => {
  for (const [name, out, why] of [
    ['collected no tests (exit 5)', { exitCode: 5, stdout: 'no tests ran in 0.01s', stderr: '' }, 'no tests collected'],
    ['a python without pytest', { exitCode: 1, stdout: '', stderr: '/usr/bin/python3: No module named pytest' }, 'pytest is not installed'],
  ] as const) {
    test(`pytest ${name}: recorded as not run, the builder is not sent back`, async ($, on) => {
      const w = engine(on, { files: ['package.json', 'node_modules', 'conftest.py'], outputs: { 'python -m pytest -q': { ...out } } })
      await startRun($)
      await answer($, 'a1', SPEC_ANSWER)
      await command($, 'plan-approved')
      await answer($, 'a2', 'built')
      await settled()
      expect(w.ran).toContain('python -m pytest -q')
      expect(w.spawned.filter(a => a.subagentType === 'factory:builder')).toHaveLength(1)
      expect(Object.entries(w.written).find(([k]) => /checks\.md$/.test(k))?.[1]).toContain(`– (${why}) python -m pytest -q`)
      expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toContain(`not run (${why}): python -m pytest -q`)
    })
  }
})

describe('the parsers', () => {
  test('tasks, with priorities and what they need', () => {
    expect(parseTasks(SPEC_ANSWER)).toEqual([
      { title: 'Token bucket core', priority: 'high', dependsOn: [] },
      { title: 'Middleware with Retry-After', priority: 'high', dependsOn: [1] },
      { title: 'Tests for bursts', priority: 'medium', dependsOn: [1, 2] },
    ])
    expect(parseTasks('no list here')).toEqual([])
  })

  test('verdicts: no verdict and a PASS with a blocker are changes', () => {
    expect(parseVerdict(PASS).state).toBe('pass')
    expect(parseVerdict(CHANGES)).toEqual({ state: 'changes', findings: [{ severity: 'major', where: 'src/mw.ts:12', text: 'Retry-After is in ms, not seconds' }] })
    expect(parseVerdict('looks fine').state).toBe('changes')
    expect(parseVerdict('VERDICT: PASS\n- [blocker] a.ts:1 secret in code').state).toBe('changes')
    // A PASS that lists a major finding disagrees with itself: changes, like a blocker. A minor one may stand under a pass.
    expect(parseVerdict('VERDICT: PASS\nFINDINGS:\n- [major] a.ts:1 wrong').state).toBe('changes')
    expect(parseVerdict('VERDICT: PASS\nFINDINGS:\n- [minor] a.ts:1 a name could be clearer').state).toBe('pass')
  })

  test('decisions: no decision is none (null); both is an escalation', () => {
    expect(parseDecision('DECISION: APPROVE\nREASON: good')).toEqual({ decision: 'APPROVE', reason: 'good' })
    expect(parseDecision('hmm').decision).toBeNull()
    expect(parseDecision('DECISION: APPROVE\nOn reflection:\nDECISION: ESCALATE').decision).toBe('ESCALATE')
    expect(parseDecision('DECISION: ESCALATE\nDECISION: APPROVE\nREASON: fine').decision).toBe('ESCALATE')
  })

  test("an answer that echoes the prompt's template is read by its own line, not the template's first option", () => {
    expect(parseDecision('End with DECISION: APPROVE or DECISION: ESCALATE and a REASON: line.\nDECISION: ESCALATE\nREASON: x')).toEqual({ decision: 'ESCALATE', reason: 'x' })
    expect(parseDecision('DECISION: APPROVE or DECISION: ESCALATE').decision).toBeNull()
    expect(parseVerdict('The format is VERDICT: PASS or VERDICT: CHANGES.\nVERDICT: CHANGES\nFINDINGS:\n- [major] a.ts:1 wrong').state).toBe('changes')
    expect(parseVerdict('VERDICT: PASS or VERDICT: CHANGES').state).toBe('changes')
    // Two verdicts that disagree: changes, whichever came last.
    expect(parseVerdict('VERDICT: CHANGES\nOn a second look it is fine.\nVERDICT: PASS')).toMatchObject({ state: 'changes', findings: [{ text: 'The reviewer gave both VERDICT: PASS and VERDICT: CHANGES.' }] })
    expect(parseVerdict('Last round: VERDICT: PASS\nVERDICT: CHANGES\n- [major] a.ts:1 wrong').state).toBe('changes')
  })

  test('the plan prompt quotes the feature as JSON, so a quote in it stays inside the string', () => {
    const run = { feature: 'Say "hi" on start', specFile: 'docs/specs/say-hi.md', tasks: [] } as never
    expect(planPrompt(run)).toContain('with goal "Say \\"hi\\" on start", source')
  })

  test('a feature loses a paste wrapper', () => {
    expect(cleanFeature('<pasted_content id="x">\n  Fix it  \n</pasted_content id="x">')).toBe('Fix it')
  })

  test('checks: the option splits into argv, detection reads the project', () => {
    expect(splitChecks('npm test; npm run lint\ngo vet ./...')).toEqual([['npm', 'test'], ['npm', 'run', 'lint'], ['go', 'vet', './...']])
    expect(detectChecks(['package.json'], '{"scripts":{"test":"x","lint":"y"}}')).toEqual([['npm', 'test'], ['npm', 'run', 'lint']])
    expect(detectChecks(['go.mod'], null)).toEqual([['go', 'test', './...']])
    expect(detectChecks([], null)).toEqual([])
  })

  test('setup: the lockfile, only when node_modules is missing', () => {
    expect(detectSetup(['package.json', 'pnpm-lock.yaml'])).toEqual(['pnpm', 'install', '--frozen-lockfile'])
    expect(detectSetup(['package.json', 'package-lock.json'])).toEqual(['npm', 'ci'])
    expect(detectSetup(['package.json'])).toEqual(['npm', 'install'])
    expect(detectSetup(['package.json', 'node_modules', 'package-lock.json'])).toBeNull()
    expect(detectSetup(['go.mod'])).toBeNull()
  })
})

describe('the models follow the size of the feature', () => {
  const LARGE = SPEC_ANSWER.replace('TASKS:', 'SIZE: large\nTASKS:')
  const models = (w: { spawned: Spawned[] }) => Object.fromEntries(w.spawned.map(x => [x.subagentType.replace('factory:', ''), x.model]))

  test('the spec-writer is asked for a size, and its line is read', () => {
    expect(specPrompt({ feature: 'x', specFile: 'docs/specs/x.md' } as never)).toMatch(/^SIZE: small, medium or large$/m)
    expect(parseSize('Wrote it.\nSIZE: Large\nTASKS:\n1. [high] a')).toBe('large')
    expect(parseSize('size: small')).toBe('small')
    expect(parseSize(SPEC_ANSWER)).toBeNull()
    expect(parseSize('SIZE: huge')).toBeNull()
  })

  test('auto: sonnet builds unless the feature is large; opus reviews security and approves; fixed ignores the size', () => {
    expect(modelsFor('medium', 'auto')).toEqual({ spec: 'sonnet', builder: 'sonnet', security: 'opus', code: 'sonnet', approver: 'opus', skeptic: 'sonnet', extra: 'sonnet' })
    expect(modelsFor(null, 'auto').builder).toBe('sonnet')
    expect(modelsFor('large', 'auto').builder).toBe('opus')
    expect(modelsFor('large', 'fixed').builder).toBe('sonnet')
  })

  test('a large feature: the builder is spawned on opus, and the pane says so', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', LARGE)
    // goal-run approves the plan: its dialog or pane passes it on.
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    expect(models(w)).toEqual({ 'spec-writer': 'sonnet', builder: 'opus', 'security-reviewer': 'opus', 'code-reviewer': 'sonnet' })
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await texts(pane)).toMatch(/spec-writer \(sonnet\) · 3 tasks, large[\s\S]*builder \(opus\)/)
    await pane.unmount()
  })

  test('no size line: the defaults', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(models(w).builder).toBe('sonnet')
  })

  test('with models fixed, a large feature still builds on sonnet', { options: { models: 'fixed' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', LARGE)
    // goal-run approves the plan: its dialog or pane passes it on.
    await command($, 'plan-approved')
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder', model: 'sonnet' })
  })
})

describe('starting a run, and its questions, in the main conversation', () => {
  test('Claude starts a run with the start tool; not from inside a subagent', async ($, on) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const r = await $.tool.call({ tool: 'mcp__factory__start', feature: 'Rate limiter, per ROUTER.md', followupId: 'k9' } as never)
    await settled()
    expect(String(r.result)).toMatch(/^Factory run started: Rate limiter, per ROUTER\.md\.[\s\S]*don't start it yourself/)
    expect(last(w)).toMatchObject({ subagentType: 'factory:spec-writer' })
    const denied = await $.tool.call({ tool: 'mcp__factory__start', feature: 'x', agentId: 'a7' } as never)
    expect(JSON.stringify(denied)).toMatch(/Only the main conversation/)
  })

  test('/factory with nothing running asks Claude to start one from the conversation', async ($, on) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    expect(await command($, '')).toBe('Asked Claude to start a run from what this conversation is working on.')
    await w.clock.advance(10)
    await settled()
    expect(w.sent.at(-1)).toMatch(/^Start a factory run on the work this conversation is about: call mcp__factory__start/)
    expect(w.spawned).toHaveLength(0)
  })

  test('without goal-run the plan is asked in a dialog: approved, the builder starts', async ($, on) => {
    const w = engine(on, { goalRun: false, answers: ['Approve and build'] })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    expect(w.asked.at(-1)).toMatch(/^The factory's plan for "Rate limiter"[\s\S]*1\. \[high\] Token bucket core/)
    expect(last(w)).toMatchObject({ id: 'a2', subagentType: 'factory:builder' })
  })

  test('the dialog\'s Other text sends the spec back with it; dismissed, the band still asks', async ($, on) => {
    const w = engine(on, { goalRun: false, answers: ['Split the middleware task'] })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    expect(last(w)).toMatchObject({ id: 'a2', subagentType: 'factory:spec-writer' })
    expect(last(w).prompt).toContain('The person asked for changes to your earlier spec: Split the middleware task')
    await answer($, 'a2', SPEC_ANSWER)
    expect(w.spawned).toHaveLength(2)
    expect(await bandText($)).toMatch(/waiting for you to approve the plan/)
  })
})

describe('a reviewer or the approver that fails is retried, never approved past', () => {
  test('an approver that failed offers Retry, not Approve PR; Retry runs it again', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(last(w)).toMatchObject({ id: 'a5', subagentType: 'factory:approver' })
    await answer($, 'a5', 'boom', 'error')
    await answer($, 'a6', 'overloaded', 'error')
    const t = await bandText($)
    expect(t).toMatch(/The approver stopped before deciding/)
    expect(t).not.toMatch(/Approve PR/)
    expect(await command($, 'approve')).toMatch(/^Nothing to approve/)
    await command($, 'retry')
    expect(last(w)).toMatchObject({ id: 'a7', subagentType: 'factory:approver' })
  })

  test('an approver that answered with no DECISION decided nothing: Retry, not Approve PR', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'The change looks reasonable overall.')
    const t = await bandText($)
    expect(t).toMatch(/gave no DECISION line\. Retry runs it again/)
    expect(t).not.toMatch(/Approve PR/)
    expect(await command($, 'approve')).toMatch(/^Nothing to approve/)
    await command($, 'retry')
    expect(last(w)).toMatchObject({ subagentType: 'factory:approver' })
  })

  test("a reviewer that failed doesn't send the builder back: Retry runs that reviewer alone", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', 'x', 'error')
    await answer($, 'a5', 'overloaded', 'error')
    await answer($, 'a4', PASS)
    expect(w.spawned.map(s => s.subagentType)).not.toContain('factory:approver')
    expect(w.spawned.filter(s => s.subagentType === 'factory:builder')).toHaveLength(1)
    expect(await bandText($)).toMatch(/The security review didn't run; Retry runs it again/)
    const sec = () => w.spawned.filter(s => s.subagentType === 'factory:security-reviewer').length
    const before = sec()
    await command($, 'retry')
    expect(sec()).toBe(before + 1)
    expect(w.spawned.filter(s => s.subagentType === 'factory:code-reviewer')).toHaveLength(1)
  })
})

describe('later rounds, the person sending it back, and role skills', () => {
  // Without the skeptic: what the builder gets back. (The skeptic's own tests are below.)
  test('round 2 goes back to the builder that built it, with only what to fix', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on, { delivers: true })
    await toReviews($)
    await answer($, 'a3', CHANGES)
    await answer($, 'a4', PASS)
    expect(w.spawned.filter(s => s.subagentType === 'factory:builder')).toHaveLength(1)
    expect(w.sends).toHaveLength(1)
    expect(w.sends[0]!.to).toBe('a2')
    expect(w.sends[0]!.text).toMatch(/^Another round on the change you built for: Rate limiter[\s\S]*\[major\] src\/mw\.ts:12 Retry-After is in ms/)
    expect(w.sends[0]!.text).not.toContain('Implement the spec')
    // Its answer is the same agent's: the run goes on to the checks and a second review round.
    await answer($, 'a2', 'Fixed, committed.')
    expect(w.spawned.slice(-2).map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
  })

  // Without the skeptic: what the builder gets back. (The skeptic's own tests are below.)
  test('a builder that cannot take the message: a new one gets the whole job', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', CHANGES)
    await answer($, 'a4', PASS)
    expect(w.sends).toHaveLength(1)
    expect(last(w)).toMatchObject({ id: 'a5', subagentType: 'factory:builder' })
    expect(last(w).prompt).toMatch(/Skill\(factory:builder\)[^\n]*\n\nImplement the spec/)
  })

  test('/factory rework sends the change back with your words, once the run waits for you', async ($, on) => {
    const w = engine(on, { delivers: true })
    await toReviews($)
    expect(await command($, 'rework use seconds')).toMatch(/^Not now: the run is/)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    expect(await command($, 'rework')).toBe('Say what to change: /factory rework <what to change>')
    expect(await command($, 'rework Retry-After must be in seconds')).toBe('Sent back to the builder: Retry-After must be in seconds')
    expect(w.sends.at(-1)!.text).toContain('The person sent the change back: Retry-After must be in seconds')
    expect(await bandText($)).toMatch(/reworking it as you asked/)
  })

  test('skills: each role loads its own first, and gets the Skill tool', { options: { skills: 'spec=spec-pack; code=org:code-review, unit-test; security=none; nobody=x' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await toReviews($)
    expect(w.spawned[0]!.prompt).toMatch(/^Before anything else, load this skill with the Skill tool and follow it for this job: Skill\(spec-pack\)\./)
    expect(w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt).toMatch(/^Before anything else, load these skills[^\n]*Skill\(org:code-review\), Skill\(unit-test\)/)
    // Not named in the option: the factory's own skill. Named none: no skill at all.
    expect(w.spawned.find(s => s.subagentType === 'factory:builder')!.prompt).toMatch(/^Before anything else, load this skill[^\n]*Skill\(factory:builder\)/)
    expect(w.spawned.find(s => s.subagentType === 'factory:security-reviewer')!.prompt).toMatch(/^Review the change/)
    expect(w.registered.find(r => r.name === 'spec-writer')!.tools).toContain('Skill')
    expect(w.registered.find(r => r.name === 'approver')!.tools).toContain('Skill')
    expect(w.registered.find(r => r.name === 'security-reviewer')!.tools).not.toContain('Skill')
  })

  test('the skills option, read', () => {
    expect(parseSkills('spec=spec-pack; builder = unit-test , architecture;code=;x=y; approver=org:approve')).toEqual({ spec: ['spec-pack'], builder: ['unit-test', 'architecture'], approver: ['org:approve'] })
    expect(parseSkills('')).toEqual({})
    expect(parseSkills('security=none')).toEqual({ security: [] })
  })
})

describe('what the factory did, and the PR asked in the conversation', () => {
  test("every step's words go to the run's record beside the worktree; the pane says what changed", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    const files = Object.keys(w.written).filter(p => p.startsWith('/repo/.factory/rate-limiter.record/')).map(p => p.split('/').pop())
    expect(files).toEqual(['01-spec-writer.md', '02-builder-round-1.md', '03-changes-after-builder-round-1.md', '04-checks.md', 'diff-round-1.patch'])
    expect(w.written['/repo/.factory/rate-limiter.record/02-builder-round-1.md']).toBe('# builder, round 1\n\nModel asked: sonnet; ran on: no step seen.\n\nbuilt\n')
    expect(w.written['/repo/.factory/rate-limiter.record/04-checks.md']).toMatch(/^# checks\n\n✓ npm test/)
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await texts(pane)).toMatch(/Changed: 1 file changed · built \| What each step said: \/repo\/\.factory\/rate-limiter\.record\//)
    await pane.unmount()
  })

  test('approved: the PR is asked in a dialog with what changed; Open the PR opens it', async ($, on) => {
    const w = engine(on, { answers: ['Open the PR'] })
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: spec met')
    expect(w.asked.at(-1)).toMatch(/^The factory's change for "Rate limiter" was approved[\s\S]*Changed: 1 file changed · built[\s\S]*Branch factory\/rate-limiter; what each step said is in \/repo\/\.factory\/rate-limiter\.record\//)
    expect(w.sent.at(-1)).toMatch(/factory\/rate-limiter/)
  })

  test("escalated: the dialog's Other text sends it back to the builder", async ($, on) => {
    const w = engine(on, { delivers: true, answers: ['Keep the memory store, add a TODO for Redis'] })
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: ESCALATE\nREASON: the spec asks for Redis, the build uses memory')
    expect(w.asked.at(-1)).toMatch(/was escalated by the approver[\s\S]*Approve it anyway\?/)
    expect(w.sends.at(-1)!.text).toContain('The person sent the change back: Keep the memory store, add a TODO for Redis')
  })
})

describe('a long feature reads as a short title', () => {
  const LONG = 'Fix the 9 model-router issues in ROUTER_ISSUES.md, in both register.tsx and register-router.tsx. Regression tests for each fix, then regenerate the plugin and run the checks. Do not commit or push.'

  test('its first sentence, clipped; a short one as it is', () => {
    expect(titleOf(LONG)).toBe('Fix the 9 model-router issues in ROUTER_ISSUES.md, in both…')
    expect(titleOf('Rate limiter')).toBe('Rate limiter')
    expect(titleOf('Add a cache. Then more.')).toBe('Add a cache.')
  })

  test('the band shows the title on one line; the pane has the whole request under it', async ($, on) => {
    engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await $.command.run({ command: 'factory', args: LONG } as never)
    await settled()
    const t = await bandText($)
    expect(t).toMatch(/^🏭 Fix the 9 model-router issues in ROUTER_ISSUES\.md, in both… \| ▱+ \d+% \| · writing the spec/)
    expect(t).not.toContain('Do not commit')
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    expect(await texts(pane)).toContain('Do not commit or push.')
    await pane.unmount()
  })
})

describe("the builder marks goal-run's tasks only when they are the factory's", () => {
  test('goal-run kept your own goal: the builder is not told to mark its t1, t2...', async ($, on) => {
    const w = engine(on, { answers: ['Approve and build'], keepsGoal: true })
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await $.tool.call({ tool: PLAN, goal: 'Rate limiter', source: 'factory', tasks: [{ title: 'x', priority: 'high' }] } as never)
    await settled()
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder' })
    expect(last(w).prompt).not.toContain('mcp__goal-run__update')
    expect(last(w).prompt).toContain('The tasks:\n- t1: Token bucket core')
  })

  // goal-run numbers the plan in its own order (priority, then dependencies), not the spec's.
  const OUT_OF_ORDER = 'Wrote docs/specs/rate-limiter.md.\nTASKS:\n1. [low] Write docs\n2. [high] Core'
  const IDS = [{ id: 't1', title: 'Core' }, { id: 't2', title: 'Write docs' }]

  test("approved in goal-run's dialog: the builder is given goal-run's ids for each task", async ($, on) => {
    const w = engine(on, { planResult: planApprovedForFactory(IDS) })
    await startRun($)
    await answer($, 'a1', OUT_OF_ORDER)
    await $.tool.call({ tool: PLAN, goal: 'Rate limiter', source: 'factory', tasks: [{ title: 'Write docs', priority: 'low' }, { title: 'Core', priority: 'high' }] } as never)
    await settled()
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder' })
    expect(last(w).prompt).toContain('then done):\n- t1: Core\n- t2: Write docs')
  })

  test("goal-run's answer sent as a command reaches the factory when its own hook doesn't (the mods' order), once", async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', OUT_OF_ORDER)
    // No plan tool call reaches the factory's hook here: only goal-run's command.
    expect(await command($, factoryPlanResultArgs(planApprovedForFactory(IDS)))).toMatch(/has goal-run's answer/)
    await settled()
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder' })
    expect(last(w).prompt).toContain('then done):\n- t1: Core\n- t2: Write docs')
    // The hook heard it too, or the command came twice: one builder.
    await command($, factoryPlanResultArgs(planApprovedForFactory(IDS)))
    await settled()
    expect(w.spawned.filter(a => a.subagentType === 'factory:builder')).toHaveLength(1)
  })

  test("goal-run's changes and its kept goal, sent as commands: the spec is revised; the factory asks once", async ($, on) => {
    const w = engine(on, { answers: [''] })
    await startRun($)
    await answer($, 'a1', OUT_OF_ORDER)
    await command($, factoryPlanResultArgs(PLAN_KEPT_FOR_FACTORY))
    await command($, factoryPlanResultArgs(PLAN_KEPT_FOR_FACTORY))
    await settled()
    expect(w.asked.filter(q => /^The factory's plan for/.test(q))).toHaveLength(1)
    await command($, factoryPlanResultArgs(planChangesForFactory('Split the core task')))
    await settled()
    expect(last(w)).toMatchObject({ subagentType: 'factory:spec-writer' })
    expect(last(w).prompt).toContain('Split the core task')
  })

  test('a mistyped subcommand while a run goes is named as one, not taken for a new feature', async ($, on) => {
    engine(on)
    await startRun($)
    await answer($, 'a1', OUT_OF_ORDER)
    expect(await command($, 'plan-approve')).toMatch(/^"\/factory plan-approve" isn't a factory command\. .*plan-approved/)
    expect(await command($, 'Add a cache to the API')).toMatch(/^A factory run is already going/)
  })

  test('/factory approve on a plan goal-run holds says how to start it if goal-run already approved it', async ($, on) => {
    engine(on)
    await startRun($)
    await answer($, 'a1', OUT_OF_ORDER)
    expect(await command($, 'approve')).toMatch(/If goal-run already shows it approved, \/factory plan-approved starts the build/)
  })

  test("approved in the Goal pane: /factory plan-approved carries goal-run's ids", async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', OUT_OF_ORDER)
    await command($, factoryPlanApprovedArgs(IDS))
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder' })
    expect(last(w).prompt).toContain('- t1: Core\n- t2: Write docs')
  })

  test("the factory's plan is the session goal: the builder marks its tasks", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(w.spawned.find(s => s.subagentType === 'factory:builder')!.prompt).toContain('mark each with mcp__goal-run__update')
  })
})

describe('the code map: what the spec-writer read, passed on', () => {
  test('the spec ends with a code map; the builder and the reviewers start from it', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(w.spawned[0]!.prompt).toMatch(/End the spec file with a "## Code map" section[^\n]*path:start-end[^\n]*signatures of the types/)
    expect(w.spawned.find(s => s.subagentType === 'factory:builder')!.prompt).toMatch(/Start from the spec's "Code map"[^\n]*never read a large file[^\n]*whole/)
    for (const t of ['factory:security-reviewer', 'factory:code-reviewer']) {
      expect(w.spawned.find(s => s.subagentType === t)!.prompt).toMatch(/Start from the diff and the spec's "Code map"/)
    }
  })
})

describe('a builder that stopped carries on, instead of starting over', () => {
  const LIMIT = "You've hit your individual spend limit · visit https://claude.ai/admin-settings/usage to raise it"
  const toBuilder = async ($: Engine) => {
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    // goal-run approves the plan: its dialog or pane passes it on.
    await command($, 'plan-approved')
  }

  test('a spend limit: no switch to another model; Retry sends the same builder on', async ($, on) => {
    const w = engine(on, { delivers: true })
    await toBuilder($)
    expect(last(w)).toMatchObject({ id: 'a2', subagentType: 'factory:builder' })
    await answer($, 'a2', LIMIT, 'error')
    expect(w.spawned).toHaveLength(2)
    expect(await bandText($)).toMatch(/Retry once the limit is lifted: the same builder carries on/)
    await command($, 'retry')
    expect(w.spawned).toHaveLength(2)
    expect(w.sends.at(-1)).toMatchObject({ to: 'a2' })
    expect(w.sends.at(-1)!.text).toMatch(/^You stopped before finishing \(an API error ended it: You've hit your individual spend limit[^)]*\)\. Carry on from where you stopped: check `git status` and `git log`/)
    await answer($, 'a2', 'Done, committed.')
    expect(w.spawned.slice(-2).map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
  })

  test("a builder that can't be sent on: the new one is told what is already in the worktree", async ($, on) => {
    const w = engine(on, { dirty: true })
    await toBuilder($)
    await answer($, 'a2', LIMIT, 'error')
    await command($, 'retry')
    expect(last(w)).toMatchObject({ id: 'a3', subagentType: 'factory:builder' })
    expect(last(w).prompt).toMatch(/A builder before you started this job and stopped[\s\S]*Uncommitted changes:\n- M src\/mw\.ts[\s\S]*Implement the spec/)
  })

  test("another API error still tries the session's model once, with the skill line once", async ($, on) => {
    const w = engine(on)
    await toBuilder($)
    await answer($, 'a2', 'model not available', 'error')
    expect(last(w)).toMatchObject({ id: 'a3', subagentType: 'factory:builder' })
    expect(last(w).model).toBeUndefined()
    expect(last(w).prompt.match(/Before anything else/g)).toHaveLength(1)
  })

  test('the progress note, from git', () => {
    expect(progressNote('', '')).toBe('')
    expect(progressNote('abc123 add bucket\n', ' M src/a.ts\n?? src/b.ts\n')).toBe([
      "A builder before you started this job and stopped; its work is in this worktree. Start from it, check it against the spec, and do what is left; don't redo it.",
      'Its commits (newest first):', '- abc123 add bucket', 'Uncommitted changes:', '- M src/a.ts', '- ?? src/b.ts',
    ].join('\n'))
  })
})

describe("git's view of the builder's new files", () => {
  test('-z -uall: each file on its own, unquoted, a rename\'s old path skipped', () => {
    expect(untrackedOf(['?? app/.env', '?? app/index.js', 'R  new.ts', 'old.ts', '?? שלום.ts', ' M x.ts', ''].join('\0'))).toEqual(['app/.env', 'app/index.js', 'שלום.ts'])
    expect(untrackedOf('')).toEqual([])
  })

  test('a sample .env, a test fixture key, and source in a folder named build or dist are kept', () => {
    for (const p of ['.env.example', 'app/.env.sample', 'tests/fixtures/server.pem', 'test/certs/client.key', 'cmd/build/main.go', 'src/dist/index.ts', 'web/dist/x.js']) expect([p, neverCommit(p)]).toEqual([p, false])
    for (const p of ['.env', 'app/.env.local', 'certs/server.key', 'deploy/prod.pem', 'node_modules/a.js', 'svc/.venv/bin/python', 'pkg/__pycache__/x.pyc']) expect([p, neverCommit(p)]).toEqual([p, true])
  })

  test('in a new folder, the .env is left out and the rest kept', () => {
    const files = untrackedOf('?? app/.env\0?? app/index.js\0')
    expect(files.filter(f => !neverCommit(f))).toEqual(['app/index.js'])
    expect(files.filter(neverCommit)).toEqual(['app/.env'])
  })

  test('what was left out reads by folder', () => {
    expect(leftOut(['node_modules/a/b.js', 'node_modules/c.js', 'app/.env', 'key.pem'])).toEqual(['node_modules/', 'app/.env', 'key.pem'])
  })
})

describe('commands the factory found run only once you let them', () => {
  test('asked before the first checks, with the exact commands; not now: the run waits, Retry asks again', async ($, on) => {
    const w = engine(on, { files: ['package.json'], checksOk: null })
    await toReviews($)
    expect(w.asked.at(-1)).toMatch(/^Before the factory runs the checks it found in the project, in \/repo\/\.factory\/rate-limiter:\n\$ npm install\n\$ npm test\n/)
    expect(w.ran).not.toContain('npm install')
    expect(w.ran).not.toContain('npm test')
    expect(await bandText($)).toMatch(/The checks wait for your OK/)
    expect(w.spawned.map(s => s.subagentType)).not.toContain('factory:code-reviewer')
  })

  test('let run once, not asked again until the builder changes what they run', async ($, on) => {
    const w = engine(on, { delivers: true })
    await toReviews($)
    expect(w.asked.filter(q => q.startsWith('Before the factory runs')).length).toBe(1)
    expect(w.ran).toContain('npm test')
    // Round 2 with nothing changed in what the checks run: not asked.
    await answer($, 'a3', CHANGES)
    await answer($, 'a4', PASS)
    await answer($, 'a2', 'Fixed.')
    expect(w.asked.filter(q => q.startsWith('Before the factory runs')).length).toBe(1)
    // The person sends it back, and this time the builder changes package.json: asked again.
    await answer($, 'a5', PASS)
    await answer($, 'a6', PASS)
    await answer($, 'a7', 'DECISION: APPROVE\nREASON: ok')
    w.setConfig('c1')
    await command($, 'rework use seconds')
    await answer($, 'a2', 'Fixed again.')
    expect(w.asked.filter(q => q.startsWith('Before the factory runs')).length).toBe(2)
    expect(w.asked.at(-1)).toMatch(/The builder changed what these run: package\.json\. Look at that diff/)
  })

  test("the project's .factory/checks.json is read from the repository's root, where the person keeps it", async ($, on) => {
    const w = engine(on)
    w.written['/repo/.factory/checks.json'] = '["make verify"]'
    await toReviews($)
    expect(w.ran).toContain('make verify')
    expect(w.ran).not.toContain('npm test')
  })

  test('a checks file only inside the worktree, where the builder writes, is not used', async ($, on) => {
    const w = engine(on, { files: ['package.json', 'node_modules', '.factory'] })
    w.written['/repo/.factory/rate-limiter/.factory/checks.json'] = '["make verify"]'
    await toReviews($)
    expect(w.ran).not.toContain('make verify')
    expect(w.ran).toContain('npm test')
  })

  // Without the skeptic: what the builder gets back. (The skeptic's own tests are below.)
  test('the question says it runs the code the builder wrote; .npmrc or a jest config changed asks again', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on, { delivers: true })
    await toReviews($)
    expect(w.asked.find(q => q.startsWith('Before the factory runs'))).toMatch(/They run the code the builder wrote, its tests and config included, outside your permission prompts/)
    const asked = () => w.asked.filter(q => q.startsWith('Before the factory runs')).length
    const watched = w.ran.find(c => c.startsWith('git log -1 --format=%H HEAD --'))!
    for (const f of ['.npmrc', 'jest.config.*', 'pom.xml', 'build.gradle.kts', '*.csproj', 'Makefile', 'conftest.py']) expect(watched).toContain(`:(glob)**/${f}`)
    expect(watched).toContain(' .factory/checks.json')
    await answer($, 'a3', CHANGES)
    await answer($, 'a4', PASS)
    w.setConfig('npmrc-changed')
    await answer($, 'a2', 'Fixed.')
    expect(asked()).toBe(2)
  })

  test('with the checks and setup options set, nothing is asked', { options: { checks: 'npm test', setup: 'npm ci' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await toReviews($)
    expect(w.asked.filter(q => q.startsWith('Before the factory runs'))).toEqual([])
    expect(w.ran).toContain('npm test')
  })
})

describe('a run\'s name from a feature in any script', () => {
  test('Latin as before; Hebrew gets a stable hash, different features different names, git-ref-safe', () => {
    expect(slugOf('Rate limiter for the API')).toBe('rate-limiter-for-the-api')
    const a = slugOf('תקן את הראוטר')
    const b = slugOf('הוסף מטמון')
    expect(a).toMatch(/^feature-[0-9a-z]{7}$/)
    expect(a).toBe(slugOf('תקן את הראוטר'))
    expect(a).not.toBe(b)
    expect(slugOf('תקן את model-router לפי ROUTER_ISSUES.md')).toMatch(/^model-router-router-issues-md-[0-9a-z]{7}$/)
    expect(slugOf('x'.repeat(100) + ' שלום').length).toBeLessThanOrEqual(48)
  })
})

describe('the frame timer', () => {
  test('runs only while a run is live', async ($, on) => {
    let frames = 0
    on('state.set', (_, e, next) => {
      if ((e as { key?: string }).key === 'frame') frames++
      return next(e)
    })
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await w.clock.advance(5_000)
    expect(frames).toBe(0)
    await command($, 'Rate limiter')
    await w.clock.advance(1_400)
    expect(frames).toBeGreaterThan(0)
    await command($, 'stop')
    await w.clock.advance(1_400)
    const after = frames
    await w.clock.advance(5_000)
    expect(frames).toBe(after)
  })
})

describe("a check whose program isn't installed is skipped, not failed", () => {
  test('not installed (spawn ENOENT): no builder round for it; the approver is told', { options: { checks: 'mvn -q test; npm test' } } as never, async ($: Engine, on: On) => {
    const w = engine(on, { missing: ['mvn -q test'] })
    await toReviews($)
    // Straight on to the reviewers: the builder isn't sent to install maven.
    expect(w.spawned.filter(s => s.subagentType === 'factory:builder')).toHaveLength(1)
    expect(w.spawned.slice(-2).map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    const prompt = last(w).prompt
    expect(prompt).toContain('mvn -q test not installed, not run, npm test passed')
    expect(prompt).toContain('Not installed here, so not run: mvn -q test.')
  })

  test('exit 127 from a check that started (a script whose inner command is missing) is a failure', { options: { checks: 'sh-missing; npm test' } } as never, async ($: Engine, on: On) => {
    const w = engine(on)
    await toReviews($)
    // The builder gets a round for it, as for any red check, and no reviewer starts yet.
    expect(last(w)).toMatchObject({ subagentType: 'factory:builder' })
    expect(last(w).prompt).toContain('$ sh-missing')
  })

  test('a timeout is a failure, not a missing program', () => {
    expect(couldNotStart(new Error('spawn mvn ENOENT'))).toBe(true)
    expect(couldNotStart(new Error('the command timed out after 600000 ms'))).toBe(false)
    expect(couldNotStart('Timeout: still running')).toBe(false)
  })

})

describe('with no check run, an approval is the person\'s call', () => {
  test('the approver is told; its APPROVE becomes an escalation the person can approve past', async ($, on) => {
    const w = engine(on, { files: [], pkg: '{}' })
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(last(w).prompt).toContain('after the last build: NONE RAN.')
    expect(last(w).prompt).toContain('No check ran: an APPROVE goes to the person as an escalation')
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: tests read fine')
    const t = await bandText($)
    expect(t).toMatch(/no check ran, so nothing was verified by running it/)
    expect(t).not.toMatch(/Open the PR when you're ready/)
    expect(w.asked.at(-1)).toMatch(/was escalated by the approver/)
    expect(await command($, 'approve')).toBe('Approved: Claude opens the PR.')
  })

  test('with checks that ran and passed, an APPROVE stays an approval', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(last(w).prompt).not.toContain('No check ran')
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    expect(await bandText($)).toMatch(/approved: ok\. Open the PR when you're ready/)
  })
})

describe("the approver sees what the change touched", () => {
  test('the files changed, the scope check and the open questions are in its prompt', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    const p = last(w).prompt
    expect(p).toContain('Files the change touched:\nsrc/mw.ts | 40 +++')
    expect(p).toMatch(/a file, dependency or public interface the spec doesn't name is scope it didn't ask for/)
    expect(p).toMatch(/Open questions: one the change settled by guessing/)
  })
})

describe('what the review run on PR #105 missed, asked for up front', () => {
  test('the spec lists every copy; the builder reports its open questions; reviewers check fields against real definitions', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(w.spawned[0]!.prompt).toMatch(/list every copy of the code the change touches[^\n]*in or out of scope/)
    expect(w.spawned.find(s => s.subagentType === 'factory:builder')!.prompt).toContain("For each of the spec's Open questions, say in your closing summary how you settled it.")
    const review = w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt
    expect(review).toMatch(/Read a changed file whole when it is short/)
    expect(review).toMatch(/against its real definition[^\n]*a criterion built on a field that doesn't exist is a blocker/)
  })
})

describe('the record says which model each role ran on', () => {
  test('the model asked for, and the ones its steps actually ran on', async ($, on) => {
    const w = engine(on)
    await startRun($)
    await step($, 'a1')
    await answer($, 'a1', SPEC_ANSWER)
    expect(w.written['/repo/.factory/rate-limiter.record/01-spec-writer.md']).toMatch(/^# spec-writer\n\nModel asked: sonnet; ran on: m\.\n/)
  })
})

describe('what the run review of 2026-10-29 found (L1, L2, L3, L9, L10)', () => {
  const CONTROL = 'mcp__factory__control'
  const REVIEW = 'UNDERSTOOD: limit requests per client and answer 429 with Retry-After.\nRead it.\nVERDICT: PASS\nFINDINGS: none\nNOT CHECKED:\n- the burst test under load: not run\n- [minor] a.ts:1 not an item'
  const paneText = async ($: Engine) => {
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' } as never)
    const t = await texts(pane)
    await pane.unmount()
    return t
  }

  test('the parsers: UNDERSTOOD, NOT CHECKED, the builder\'s TESTS line, a feature that says not to push', () => {
    expect(parseUnderstood(REVIEW)).toBe('limit requests per client and answer 429 with Retry-After.')
    expect(parseUnderstood('UNDERSTOOD: <what the change must do>')).toBeUndefined()
    expect(parseNotChecked(REVIEW)).toEqual(['the burst test under load: not run'])
    expect(parseNotChecked('VERDICT: PASS\nNOT CHECKED: none')).toEqual([])
    expect(parseNotChecked('VERDICT: PASS')).toBeUndefined()
    expect(parseBuilderTests('done\nTESTS: npm test -> 141 passed, 6 failed')).toEqual({ text: 'npm test -> 141 passed, 6 failed', failing: true })
    expect(parseBuilderTests('TESTS: npm test -> 12 passed, 0 failed')!.failing).toBe(false)
    expect(parseBuilderTests('TESTS: none run, no runner here')!.failing).toBe(false)
    expect(parseBuilderTests('TESTS: pytest: two tests fail')!.failing).toBe(true)
    expect(parseBuilderTests('TESTS: pytest, no failures')!.failing).toBe(false)
    expect(parseBuilderTests('no line')).toBeUndefined()
    expect(summaryOf('Changed mw.ts.\nAdded tests.\nTESTS: npm test -> 3 passed')).toBe('Changed mw.ts. Added tests.')
    expect(forbidsPush('Fix the router. Do not push.')).toBe(true)
    expect(forbidsPush("Fix it, but don't open a PR")).toBe(true)
    expect(forbidsPush('תתקן את הראוטר, אל תדחוף')).toBe(true)
    expect(forbidsPush('Send no push notifications at night')).toBe(false)
    expect(forbidsPush('Rate limiter')).toBe(false)
  })

  test('L9: every agent is given absolute paths and kept out of the main checkout', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    for (const s of w.spawned) {
      expect(s.prompt).toContain('/repo/.factory/rate-limiter/docs/specs/rate-limiter.md')
      expect(s.prompt).toMatch(/Work only in the worktree \/repo\/\.factory\/rate-limiter[^\n]*The main checkout \/repo is the person's: never cd into it/)
    }
  })

  test("L1: reviewers read the repository's rules first; the builder follows them; the approver escalates a broken one", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(w.spawned.find(s => s.subagentType === 'factory:builder')!.prompt).toMatch(/Follow the repository's CLAUDE\.md/)
    expect(w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt).toMatch(/CLAUDE\.md at the worktree's root[^\n]*a file it says is generated, edited by hand[^\n]*is a blocker/)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(last(w).prompt).toMatch(/Read the repository's CLAUDE\.md: a change to files it says are generated[^\n]*ESCALATE/)
  })

  test("L2: the builder's test run reaches the reviewers and the approver; failures turn an APPROVE into the person's call", async ($, on) => {
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    expect(last(w).prompt).toContain('TESTS: <command> -> <N passed, M failed>')
    await answer($, 'a2', 'Shortened the prompts.\nTwo caps may bite.\nTESTS: claude plugin test -> 141 passed, 6 failed')
    const review = w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt
    expect(review).toContain("The builder's summary: Shortened the prompts. Two caps may bite.")
    expect(review).toContain("The builder's own test run: claude plugin test -> 141 passed, 6 failed (it reports failures")
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(last(w).prompt).toContain("The builder's own test run: claude plugin test -> 141 passed, 6 failed")
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: spec met')
    const t = await bandText($)
    expect(t).toMatch(/the builder reported failing tests/)
    expect(t).not.toMatch(/Open the PR when you're ready/)
  })

  test("L10 and the comprehension check: what each reviewer understood and didn't check goes to the approver and the PR", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    const review = w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt
    expect(review).toMatch(/^UNDERSTOOD: <what the change must do/m)
    expect(review).toMatch(/^NOT CHECKED:$/m)
    await answer($, 'a3', REVIEW)
    await answer($, 'a4', PASS)
    const p = last(w).prompt
    expect(p).toContain('  understood: limit requests per client and answer 429 with Retry-After.')
    expect(p).toContain('  not checked: the burst test under load: not run')
    expect(p).toContain('  not checked: not said')
    expect(p).toMatch(/An acceptance criterion that no reviewer checked and no check ran for is unverified: ESCALATE/)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    expect(w.sent.at(-1)).toMatch(/Not verified[^\n]*\n- security: the burst test under load: not run/)
  })

  test('L3: the PR reads as requested until Claude reports its link; pr-opened records it', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(await $.tool.call({ tool: CONTROL, action: 'pr-opened', url: 'https://github.com/o/r/pull/7' } as never).then(r => String(r.result))).toBe('No approved factory run waits for its PR.')
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    expect(w.sent.at(-1)).toMatch(/Push branch factory\/rate-limiter \(git -C \/repo\/\.factory\/rate-limiter push -u origin factory\/rate-limiter\)/)
    expect(w.sent.at(-1)).toMatch(/call mcp__factory__control with action "pr-opened"/)
    expect(await paneText($)).toMatch(/PR requested \(Claude\)/)
    expect(await $.tool.call({ tool: CONTROL, action: 'pr-opened', url: 'not a link' } as never).then(r => String(r.result))).toMatch(/needs the PR's link/)
    expect(await $.tool.call({ tool: CONTROL, action: 'pr-opened', url: 'https://github.com/o/r/pull/7' } as never).then(r => String(r.result))).toMatch(/pull\/7/)
    expect(await paneText($)).toMatch(/✓ PR opened · https:\/\/github\.com\/o\/r\/pull\/7/)
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toMatch(/PR: opened, https:\/\/github\.com\/o\/r\/pull\/7/)
  })

  test('L3: a feature that says not to push gets the commands for the person, and no push', async ($, on) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await command($, 'Rate limiter. Do not push.')
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    await answer($, 'a2', 'built')
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    const sent = w.sent.at(-1)!
    expect(sent).toMatch(/The feature says not to push, so don't push and don't open the PR/)
    expect(sent).toMatch(/git -C \/repo\/\.factory\/[\w-]+ push -u origin factory\//)
    expect(sent).not.toMatch(/^Push branch/m)
    expect(await paneText($)).toMatch(/PR: commands handed to you/)
  })
})

describe('the doctor, and the next actions the status tool lists', () => {
  const STATUS = 'mcp__factory__status'
  const status = async ($: Engine) => String((await $.tool.call({ tool: STATUS } as never)).result)

  test('/factory doctor: the repository, the checks found, goal-run and gh, without starting a run', async ($, on) => {
    const w = engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const t = await command($, 'doctor')
    expect(t).toMatch(/^Factory doctor: ready to run\./)
    expect(t).toMatch(/✓ Git repository \/repo, detached HEAD at abc123/)
    expect(t).toMatch(/✓ Checks found: npm test\./)
    expect(t).toMatch(/✓ goal-run is installed/)
    expect(t).toMatch(/✓ gh is installed/)
    expect(w.spawned).toEqual([])
    expect(w.ran.some(c => c.startsWith('git worktree'))).toBe(false)
  })

  test('the doctor names a blocker and what to do; no checks and no goal-run are warnings', async ($, on) => {
    engine(on, { noRepo: true })
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    expect(await command($, 'doctor')).toMatch(/1 blocker[^\n]*\n✗ Not a git repository[^\n]*git init/)
  })

  test('warnings: no checks, no goal-run, uncommitted work', async ($, on) => {
    engine(on, { files: [], pkg: '{}', goalRun: false, dirty: true })
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const t = await command($, 'doctor')
    expect(t).toMatch(/^Factory doctor: a run can start; \d+ things to know/)
    expect(t).toMatch(/! \d+ uncommitted changes in your checkout: a run builds from the last commit/)
    expect(t).toMatch(/! goal-run isn't installed/)
    expect(t).toMatch(/! No checks:/)
  })

  test('the status tool with no run: the doctor, and starting one as the next action', async ($, on) => {
    engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    const t = await status($)
    expect(t).toMatch(/^No factory run in this session\.\nFactory doctor: ready to run/)
    expect(t).toMatch(/Next actions:\n- start \(you\): mcp__factory__start/)
  })

  test("an escalation's next actions are the person's: approve or rework, never a retry", async ($, on) => {
    engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(await status($)).toMatch(/Next actions:\n- add-reviewers|Next actions:\n- stop/)
    await answer($, 'a5', 'DECISION: ESCALATE\nREASON: touches auth')
    const t = await status($)
    expect(t).toMatch(/Next actions:\n- approve-pr \(the person\): \/factory approve[^\n]*not yours to approve\n- rework \(the person\)/)
    expect(t).not.toMatch(/- retry/)
  })

  test('next actions by phase: the plan is the person\'s, a stopped step is retried, a requested PR waits for its link', () => {
    const base = { phase: 'plan', gate: 'goal-run', steps: { builder: { state: 'wait' } }, blocked: null } as never as Parameters<typeof nextActionsOf>[0] & object
    expect(nextActionsOf(base, 0).map(a => `${a.action}:${a.by}`)).toEqual(['approve-plan:person', 'stop:claude'])
    expect(nextActionsOf({ ...base, phase: 'needs-human', blocked: { on: 'start', role: 'approver' }, steps: { builder: { state: 'pass' } } } as never, 0).map(a => a.action)).toEqual(['retry', 'rework', 'stop'])
    expect(nextActionsOf({ ...base, phase: 'needs-human', blocked: { on: 'base' } } as never, 0).map(a => a.action)).toEqual(['base', 'stop'])
    expect(nextActionsOf({ ...base, phase: 'done', pr: { state: 'requested' } } as never, 0).map(a => a.action)).toEqual(['pr-opened', 'start'])
    expect(nextActionsOf({ ...base, phase: 'done', pr: { state: 'opened', url: 'u' } } as never, 0).map(a => a.action)).toEqual(['start'])
    expect(nextActionsOf(null, 0).map(a => a.action)).toEqual(['start'])
  })
})

describe('what the first real run found', () => {
  test("the spec the spec-writer left uncommitted isn't a builder's work: the first builder gets no progress note", () => {
    expect(progressNote('', '?? docs/specs/rate-limiter.md\n', ['docs/specs/rate-limiter.md'])).toBe('')
    expect(progressNote('', '?? docs/specs/rate-limiter.md\n M src/mw.ts\n', ['docs/specs/rate-limiter.md'])).toMatch(/Uncommitted changes:\n- M src\/mw\.ts$/)
  })

  test('the checks question unanswered: /factory checks-ok runs exactly the commands it named, and the run goes on', async ($, on) => {
    const w = engine(on, { files: ['package.json'], checksOk: null })
    await toReviews($)
    expect(w.ran).not.toContain('npm test')
    const status = String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)
    expect(status).toMatch(/The checks wait for your OK to run what the factory found: npm install; npm test\. \/factory checks-ok runs them/)
    expect(status).toMatch(/Next actions:\n- checks-ok \(the person\): \/factory checks-ok: runs the commands the factory found \(npm install; npm test\); not yours to allow/)
    const asked = w.asked.length
    expect(await command($, 'checks-ok')).toBe('Running them: npm install; npm test. Not asked again in this run until the files that define them change.')
    expect(w.asked.length).toBe(asked)
    expect(w.ran).toContain('npm install')
    expect(w.ran).toContain('npm test')
    expect(w.spawned.map(s => s.subagentType)).toContain('factory:code-reviewer')
    expect(await command($, 'checks-ok')).toBe('No checks wait for your OK.')
  })
})

describe("the agents don't need git or a shell chain (what the first real run's refusals showed)", () => {
  test('the reviewers and the skeptic read the diff from a file the factory wrote; every prompt says one plain command per call', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    const file = '/repo/.factory/rate-limiter.record/diff-round-1.patch'
    expect(w.written[file]).toContain('+export const limit = 10')
    const review = w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt
    expect(review).toContain(`The whole diff is in ${file}: read it with the Read tool`)
    for (const s of w.spawned) expect(s.prompt).toMatch(/In Bash, one plain command per call: no cd, no git -C, no &&/)
    expect(w.spawned.find(s => s.subagentType === 'factory:builder')!.prompt).toMatch(/If a git or test command is refused, leave it: the factory commits what you leave/)
    await answer($, 'a3', PASS)
    await answer($, 'a4', CHANGES)
    expect(last(w).subagentType).toBe('factory:skeptic')
    expect(last(w).prompt).toContain(`The whole diff is in ${file}`)
  })

  test("the approver is told the checks are the factory's own run, covering a reviewer who couldn't run them", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await answer($, 'a3', PASS)
    await answer($, 'a4', PASS)
    expect(last(w).prompt).toContain("Checks the factory ran itself, in the worktree, after the last build: npm test passed. A reviewer or the builder who says it couldn't run one of these is covered by this result.")
  })
})

describe('what the setup writes is not the change (the second bench round)', () => {
  test("a lockfile npm install made in the worktree is never committed in a later round, and is listed as left out", { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on, { files: ['package.json'], setupMakes: ['package-lock.json'] })
    await toReviews($)
    expect(w.ran).toContain('npm install')
    await answer($, 'a3', CHANGES)
    await answer($, 'a4', PASS)
    expect(last(w).subagentType).toBe('factory:builder')
    await answer($, last(w).id, 'fixed')
    expect(w.ran.filter(c => c.startsWith('git add --'))).toEqual([])
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).not.toMatch(/FAILED/)
  })
})

describe('/factory review: the reviewers alone, on the change in your checkout', () => {
  const REVIEW = 'mcp__factory__review'
  const begin = async ($: Engine) => $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)

  test('no change against the base: nothing to review, nothing started', async ($, on) => {
    const w = engine(on)
    await begin($)
    expect(await command($, 'review')).toMatch(/^Nothing to review: the checkout has no change against HEAD/)
    expect(w.spawned).toEqual([])
  })

  test('the checkout against where it left the default branch: reviewers only, no worktree or spec; what stands goes to Claude', async ($, on) => {
    const w = engine(on, { mergeBase: 'def999', reviewChange: true, newFiles: ['src/new.ts', '.env'] })
    await begin($)
    const said = await command($, 'review add a token check to the middleware')
    expect(said).toMatch(/^Factory review started: security, code on the checkout against origin\/HEAD \(def999\), with 1 new file\./)
    expect(w.ran.some(c => c.startsWith('git worktree add'))).toBe(false)
    expect(w.spawned.map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
    const p = w.spawned[1]!.prompt
    expect(p).toContain('Review the change for: add a token check to the middleware')
    expect(p).toMatch(/There is no spec[^\n]*The change is the checkout \/repo against def999, uncommitted work included/)
    expect(p).toContain('New files not yet in git (not in the diff; read them whole): src/new.ts')
    expect(p).toMatch(/The whole diff is in \/repo\/\.factory\/review-[\w-]+\.record\/diff-round-1\.patch/)
    expect(p).toMatch(/change nothing/)
    expect(w.spawned[1]!.cwd).toBe('/repo')
    // A review's agent can't edit the person's checkout.
    expect(await $.tool.call({ tool: 'Edit', agentId: 'a2', file_path: '/repo/src/mw.ts' } as never).then(r => JSON.stringify(r))).toMatch(/A factory review changes no file/)
    // Nor through the shell; reading through it goes on.
    expect(await $.tool.call({ tool: 'Bash', agentId: 'a2', command: 'git stash' } as never).then(r => JSON.stringify(r))).toMatch(/changes nothing in your checkout \(changing the checkout with git\)/)
    expect(await $.tool.call({ tool: 'Bash', agentId: 'a1', command: "sed -i 's/a/b/' src/mw.ts" } as never).then(r => JSON.stringify(r))).toMatch(/editing a file in place/)
    expect(await $.tool.call({ tool: 'Bash', agentId: 'a2', command: 'git diff def999' } as never).then(r => JSON.stringify(r ?? {}))).not.toMatch(/changes nothing/)
    await answer($, 'a1', PASS)
    await answer($, 'a2', 'VERDICT: CHANGES\nFINDINGS:\n- [major] src/mw.ts:3 the token is read from the query string, so it lands in logs')
    // The skeptic first; what stands goes back to the main Claude, with no builder or approver.
    expect(last(w).subagentType).toBe('factory:skeptic')
    await answer($, 'a3', 'F1: STANDS')
    expect(w.spawned.map(s => s.subagentType)).not.toContain('factory:builder')
    expect(w.spawned.map(s => s.subagentType)).not.toContain('factory:approver')
    expect(w.sent.at(-1)).toMatch(/^The factory's reviewers \(security, code\) reviewed the change in \/repo against def999/)
    expect(w.sent.at(-1)).toContain('Fix each of these in the checkout, then say what you changed:\n- F2 code [major] src/mw.ts:3 the token is read from the query string')
    expect(w.sent.at(-1)).toContain('Minor, fix when cheap:\n- F1 security src/limit.ts:4 a name could be clearer')
    const status = String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)
    expect(status).toMatch(/Phase: done[^\n]*reviewed: 1 finding to fix, sent to Claude/)
    expect(status).toMatch(/A review of the checkout \/repo against origin\/HEAD \(def999\): reviewers only/)
  })

  test('with the skeptic off, a clean review says so; the tool starts one, a sub-agent cannot', { options: { skeptic: 'off' } } as never, async ($: Engine, on: On) => {
    const w = engine(on, { mergeBase: 'def999', reviewChange: true })
    await begin($)
    expect(String((await $.tool.call({ tool: REVIEW, focus: 'x', agentId: 'zz' } as never)).deny ?? '')).toMatch(/Only the main conversation/)
    expect(String((await $.tool.call({ tool: REVIEW, focus: 'rate limiter', reviewers: ['performance'] } as never)).result)).toMatch(/^Factory review started: security, code, performance/)
    await settled()
    await answer($, 'a1', PASS)
    await answer($, 'a2', PASS)
    await answer($, 'a3', 'VERDICT: PASS\nFINDINGS: none')
    expect(w.sent.at(-1)).toContain('No blocker or major finding.')
    expect(await command($, 'review base=nope x')).toBe('No commit or branch named nope.')
  })
})

describe('what every run measures, and the test commands every agent is given', () => {
  test("the reviewers get the project's checks the factory ran, and are told to use exactly those", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt).toContain("The project's checks, which the factory ran itself after the last build: npm test passed. To run tests yourself, use exactly these commands.")
  })

  test('a review run runs the checks it found on the checkout first, once the person lets it; the reviewers get the result', async ($, on) => {
    const w = engine(on, { mergeBase: 'def999', reviewChange: true })
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await command($, 'review x')
    expect(w.asked.at(-1)).toMatch(/^Before the factory runs the checks it found in the project, in \/repo:\n\$ npm test/)
    expect(w.ran).toContain('npm test')
    expect(w.spawned[0]!.prompt).toContain("The project's checks, which the factory ran itself on the checkout: npm test passed. To run tests yourself, use exactly these commands.")
  })

  test("a review whose checks the person doesn't let run goes on without them; failing ones go to the reviewers, not a builder; nothing is installed", async ($, on) => {
    const w = engine(on, { mergeBase: 'def999', reviewChange: true, checksOk: null, files: ['package.json'] })
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await command($, 'review x')
    expect(w.ran).not.toContain('npm test')
    expect(w.ran).not.toContain('npm install')
    expect(w.spawned.map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
    expect(w.spawned[0]!.prompt).toMatch(/No checks ran for this change: The person didn't let the found commands run \(npm test\)/)
  })

  test('a failing check in a review: the reviewers are told, and no builder is sent', { options: { checks: 'npm test' } } as never, async ($: Engine, on: On) => {
    const w = engine(on, { mergeBase: 'def999', reviewChange: true, fails: 1 })
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await command($, 'review x')
    expect(w.spawned.map(s => s.subagentType)).toEqual(['factory:security-reviewer', 'factory:code-reviewer'])
    expect(w.spawned[0]!.prompt).toContain('on the checkout: npm test FAILED')
  })

  test('the stats: time, iterations, findings, tool calls and the answers that missed a marker, in the status and the record', async ($, on) => {
    const w = engine(on)
    await toReviews($)
    await $.tool.call({ tool: 'Edit', agentId: 'a3', file_path: '/repo/.factory/rate-limiter/src/mw.ts' } as never)
    await answer($, 'a3', PASS)
    await answer($, 'a4', 'UNDERSTOOD: a limiter.\nVERDICT: PASS\nFINDINGS: none\nNOT CHECKED: none')
    await answer($, 'a5', 'DECISION: APPROVE\nREASON: ok')
    await command($, 'approve')
    const stats = w.written['/repo/.factory/rate-limiter.record/stats.md']
    expect(stats).toMatch(/^# stats\n\nTime: \d+:\d\d from start\./)
    expect(stats).toContain('Iterations: 1 builder start, 1 review round.')
    expect(stats).toContain('Findings this round: 0 blocker, 0 major, 1 minor; refuted by the skeptic so far: 0.')
    expect(stats).toMatch(/Tool calls the factory saw: security 1; refused by its guard: 0\./)
    expect(stats).toContain('Answers missing a marker their prompt asks for: builder (round 1): no TESTS line; security review (round 1): no UNDERSTOOD, NOT CHECKED.')
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toMatch(/Stats: Iterations: 1 builder start/)
  })
})

describe('what the model-router review showed', () => {
  test('a finding that runs over indented lines is read whole; the next finding or a blank line ends it', () => {
    const v = parseVerdict('VERDICT: CHANGES\nFINDINGS:\n- [minor] README.md:12 The README is out of date in three places:\n  - it says off means pass through\n  - it names a retired bundle\n- [major] a.ts:3 wrong\n\nNOT CHECKED: none')
    expect(v.findings).toEqual([
      { severity: 'minor', where: 'README.md:12', text: 'The README is out of date in three places: - it says off means pass through - it names a retired bundle' },
      { severity: 'major', where: 'a.ts:3', text: 'wrong' },
    ])
  })

  test("the reviewers cite the file's own lines, not the diff file's", async ($, on) => {
    const w = engine(on)
    await toReviews($)
    expect(w.spawned.find(s => s.subagentType === 'factory:code-reviewer')!.prompt).toContain('path:line is a line of the file itself, as Read shows it, never a line of the diff file.')
  })
})

describe("what became of each review finding: reported, kept, and added up over the repository", () => {
  const CONTROL = 'mcp__factory__control'
  const control = async ($: Engine, input: Record<string, unknown>) => String((await $.tool.call({ tool: CONTROL, ...input } as never)).result ?? '')

  test('Claude reports fixed, not-a-bug or wont-fix per id; stats, the status and findings.jsonl say so', async ($, on) => {
    const w = engine(on, { mergeBase: 'def999', reviewChange: true })
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await command($, 'review x')
    await answer($, 'a1', PASS)
    await answer($, 'a2', 'VERDICT: CHANGES\nFINDINGS:\n- [major] src/mw.ts:3 the token is read from the query string\n- [major] src/mw.ts:9 the limit is per process')
    await answer($, 'a3', 'F1: STANDS\nF2: REFUTED src/mw.ts:2 the store is shared (redis)')
    const told = w.sent.at(-1)!
    expect(told).toMatch(/report what became of every one, F1, F2, with mcp__factory__control action "findings"/)
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toMatch(/- findings \(you\): mcp__factory__control action "findings"/)
    expect(await control($, { action: 'findings', outcomes: [{ id: 'F9', outcome: 'fixed' }] })).toMatch(/^No outcome read/)
    const said = await control($, { action: 'findings', outcomes: [{ id: 'F1', outcome: 'not-a-bug', why: 'a test shows the code reads the header' }, { id: 'F2', outcome: 'fixed' }] })
    expect(said).toBe("Recorded 2 outcomes. 3 findings: 1 fixed, 1 not a bug, 1 refuted by the skeptic. False positives among those judged: 50% (1 of 2).")
    const jsonl = w.written['/repo/.factory/findings.jsonl']!.trim().split('\n').map(l => JSON.parse(l))
    expect(jsonl.map(x => [x.role, x.severity, x.outcome])).toEqual([['security', 'minor', 'not-a-bug'], ['code', 'major', 'fixed']])
    expect(jsonl[0].why).toBe('a test shows the code reads the header')
    expect(w.written[Object.keys(w.written).find(k => /review-.*\.record\/stats\.md$/.test(k))!]).toMatch(/Outcomes: 3 findings: 1 fixed, 1 not a bug, 1 refuted by the skeptic\./)
    expect(String((await $.tool.call({ tool: 'mcp__factory__status' } as never)).result)).toMatch(/Review findings in this repository so far \(\.factory\/findings\.jsonl\): 2 findings: 1 fixed, 1 not a bug\. False positives among those judged: 50%/)
  })

  test('without a review that sent findings back, there is nothing to report', async ($, on) => {
    engine(on)
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    expect(await control($, { action: 'findings', outcomes: [{ id: 'F1', outcome: 'fixed' }] })).toBe('No review findings wait for their outcomes.')
  })
})

describe('the skeptic weighs both ways: a design choice and an unverified claim are set aside, not fixed', () => {
  test('DESIGN and UNVERIFIED rulings are read, with their evidence', () => {
    const f = [0, 1, 2].map(i => ({ severity: 'minor' as const, where: `a.ts:${i}`, text: `t${i}` }))
    const { kept, dropped } = applyRulings(f, 'F1: DESIGN a.test.ts:4 asserts it\nF2: UNVERIFIED rests on the engine; a probe test would settle it\nF3: STANDS traced a.ts:2', () => false)
    expect(kept).toEqual([f[2]])
    expect(dropped.map(d => d.ruling)).toEqual(['design', 'unverified'])
  })

  test('in a review run the skeptic weighs minor findings too; what it sets aside goes back grouped, with its outcome', async ($, on) => {
    const w = engine(on, { mergeBase: 'def999', reviewChange: true })
    await $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true } as never)
    await command($, 'review x')
    await answer($, 'a1', 'VERDICT: PASS\nFINDINGS:\n- [minor] src/a.ts:1 typed text becomes the title')
    await answer($, 'a2', 'VERDICT: CHANGES\nFINDINGS:\n- [major] src/b.ts:2 the second call spawns twice\n- [major] src/c.ts:3 the token leaks')
    const sk = last(w)
    expect(sk.subagentType).toBe('factory:skeptic')
    expect(sk.prompt).toContain('F1. security [minor] src/a.ts:1 typed text becomes the title')
    expect(sk.prompt).toMatch(/F<n>: DESIGN <the test, comment or doc/)
    expect(sk.prompt).toMatch(/F<n>: UNVERIFIED <what it rests on/)
    await answer($, sk.id, 'F1: DESIGN src/a.test.ts:9 pins the rewording\nF2: UNVERIFIED rests on the engine re-running next; a probe test would settle it\nF3: STANDS c.ts:3 a bare GH_TOKEN=x shows on the card')
    const told = w.sent.at(-1)!
    expect(told).toMatch(/Fix each of these[\s\S]*src\/c\.ts:3 the token leaks/)
    expect(told).toMatch(/make these deliberate \(the person's call[^\n]*\n- security src\/a\.ts:1 typed text becomes the title: src\/a\.test\.ts:9 pins the rewording/)
    expect(told).toMatch(/couldn't check[^\n]*\n- code src\/b\.ts:2 the second call spawns twice: rests on the engine/)
    expect(await $.tool.call({ tool: 'mcp__factory__control', action: 'findings', outcomes: [{ id: 'F1', outcome: 'fixed' }] } as never).then(r => String(r.result))).toMatch(/1 fixed, 1 a design choice \(the skeptic\), 1 unverified \(the skeptic\)/)
  })
})

describe("inspector open-bugs: the factory's parsers (#8 and the lower ones)", () => {
  test('#8: a bold VERDICT or DECISION is read; the echoed template still is not', () => {
    expect(parseVerdict('**VERDICT:** PASS\nFINDINGS: none').state).toBe('pass')
    expect(parseVerdict('**VERDICT**: CHANGES\n- [major] a.ts:1 x').state).toBe('changes')
    expect(parseVerdict('VERDICT: **PASS**').state).toBe('pass')
    expect(parseDecision('**DECISION:** APPROVE\nREASON: ok').decision).toBe('APPROVE')
    expect(parseVerdict('**VERDICT:** PASS or **VERDICT:** CHANGES').findings[0]!.text).toMatch(/no VERDICT line/)
  })

  test('the needs of a task read with "and"; "all pass" is not a failing test run', () => {
    expect(parseTasks('TASKS:\n1. [high] A\n2. [high] B\n3. [low] C (needs 1 and 2)')[2]).toEqual({ title: 'C', priority: 'low', dependsOn: [1, 2] })
    expect(builderTestsOf('TESTS: npm test -> all pass after the failures were fixed')!.failing).toBe(false)
    expect(builderTestsOf('TESTS: npm test -> 3 failed')!.failing).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Inspector lead reproduction tests (2026-11-07 factory run)
// ---------------------------------------------------------------------------
// L1: applyRulings bold tolerance — fixed in route.ts, matching marker()'s #76 fix.
// L2: stoppedAgents error path — documented; store-failure reproduction blocked by framework.

describe('inspector lead L1: applyRulings bold-markdown tolerance (copy drift from #76 marker() fix)', () => {
  // Contract: skepticPrompt (flow.ts:460-465) tells the model to write
  // "F<n>: RULING <evidence>". Models routinely add bold (**) around markers.
  // marker() was fixed in #76 to tolerate bold. applyRulings now matches.

  const f = [
    { severity: 'major' as const, where: 'a.ts:1', text: 'the token is in the query string' },
    { severity: 'blocker' as const, where: 'b.ts:2', text: 'SQL injection in the filter' },
  ]
  const noSecurity = () => false

  test('baseline: plain-text rulings are parsed correctly', () => {
    const { kept, dropped } = applyRulings(f, 'F1: REFUTED a.ts:1 the token is read from a header\nF2: STANDS traced b.ts:2', noSecurity)
    expect(dropped).toHaveLength(1)
    expect(dropped[0]!.ruling).toBe('refuted')
    expect(kept).toEqual([f[1]])
  })

  test('bold around F-number: **F1**: REFUTED is parsed', () => {
    const { kept, dropped } = applyRulings(f, '**F1**: REFUTED a.ts:1 the token is read from a header\nF2: STANDS traced b.ts:2', noSecurity)
    expect(dropped).toHaveLength(1)
    expect(dropped[0]!.ruling).toBe('refuted')
    expect(kept).toEqual([f[1]])
  })

  test('bold around ruling: F1: **REFUTED** is parsed', () => {
    const { kept, dropped } = applyRulings(f, 'F1: **REFUTED** a.ts:1 the token is read from a header\nF2: STANDS traced b.ts:2', noSecurity)
    expect(dropped).toHaveLength(1)
    expect(dropped[0]!.ruling).toBe('refuted')
    expect(kept).toEqual([f[1]])
  })

  test('bold around both: **F1**: **REFUTED** is parsed', () => {
    const { kept, dropped } = applyRulings(f, '**F1**: **REFUTED** a.ts:1 the token is read from a header\n**F2**: STANDS traced b.ts:2', noSecurity)
    expect(dropped).toHaveLength(1)
    expect(dropped[0]!.ruling).toBe('refuted')
    expect(kept).toEqual([f[1]])
  })

  test('state-level outcome: a bold ruling is applied, the refuted finding is dropped', () => {
    const { kept, dropped } = applyRulings(f, '**F1**: REFUTED a.ts:1 the token is read from a header\n**F2**: STANDS traced b.ts:2', noSecurity)
    expect(kept).toEqual([f[1]])
    expect(dropped).toHaveLength(1)
    expect(dropped[0]!.ruling).toBe('refuted')
  })

  test('bold tolerance matches marker(): both parsers accept the same formatting', () => {
    expect(parseVerdict('**VERDICT:** PASS').state).toBe('pass')
    expect(parseVerdict('VERDICT: **PASS**').state).toBe('pass')
    const { dropped } = applyRulings(f, '**F1**: REFUTED evidence', noSecurity)
    expect(dropped).toHaveLength(1)
    expect(dropped[0]!.ruling).toBe('refuted')
  })

  test('all five ruling types are parsed with and without bold', () => {
    const five = [0, 1, 2, 3, 4].map(i => ({ severity: 'major' as const, where: `a.ts:${i}`, text: `t${i}` }))
    const plain = 'F1: STANDS traced\nF2: REFUTED a.ts:1 handled\nF3: DOWNGRADED only a log line, a.ts:2\nF4: DESIGN a.test.ts:4 asserts it\nF5: UNVERIFIED rests on the engine'
    const bold = '**F1**: STANDS traced\n**F2**: **REFUTED** a.ts:1 handled\nF3: **DOWNGRADED** only a log line, a.ts:2\n**F4**: DESIGN a.test.ts:4 asserts it\nF5: **UNVERIFIED** rests on the engine'
    const rPlain = applyRulings(five, plain, () => false)
    const rBold = applyRulings(five, bold, () => false)
    expect(rPlain.dropped.map(d => d.ruling)).toEqual(['refuted', 'downgraded', 'design', 'unverified'])
    expect(rBold.dropped.map(d => d.ruling)).toEqual(rPlain.dropped.map(d => d.ruling))
    expect(rBold.kept.map(f => f.where)).toEqual(rPlain.kept.map(f => f.where))
  })

  test('non-ruling prose and invalid F-ids are not matched', () => {
    const { kept, dropped } = applyRulings(f, 'The skeptic looked at F1 and found it solid.\nF99: REFUTED imaginary\nF0: REFUTED zero', noSecurity)
    expect(dropped).toHaveLength(0)
    expect(kept).toEqual(f)
  })

  test('evidence after a bold ruling is preserved', () => {
    const { dropped } = applyRulings(f, '**F1**: **REFUTED** a.ts:1 the token is read from a header, not the query string', noSecurity)
    expect(dropped[0]!.why).toBe('a.ts:1 the token is read from a header, not the query string')
  })
})

describe('inspector lead L2: tool.call guard error path — stoppedAgents read failure', () => {
  // The guard at register.tsx:1404-1443 must fail closed: a run agent's forbidden
  // call (push, deploy) is refused even when the state read fails.
  // #74 fixed read($, run) with .catch(() => null).
  // read($, stoppedAgents) at line 1413 has no .catch.
  //
  // TESTING LIMITATION: the test framework's atom store is in-memory and cannot
  // be made to throw. A faithful reproduction of "stoppedAgents read throws"
  // requires either: (a) a mock/patch of the atom read function, which the
  // bundled claude-code/testing framework does not expose, or (b) a production
  // code change to inject a failing store, which this test set is not authorized
  // to make.
  //
  // What we CAN test: the guard's behavior on stopped agents through the normal
  // path, and the .catch fallback's behavior, to document the policy gap.

  test('a stopped agent is denied any tool call through the normal (non-throwing) path', async ($, on) => {
    const w = engine(on)
    await startRun($)
    expect(await command($, 'stop')).toMatch(/Stopped/)
    // Agent a1 is now in stoppedAgents. Its tool calls should be denied.
    const read = await $.tool.call({ tool: 'Read', file_path: '/repo/src/mw.ts', agentId: 'a1' } as never)
    expect(String((read as { deny?: string }).deny)).toMatch(/factory run was stopped/)
    const bash = await $.tool.call({ tool: 'Bash', command: 'ls', agentId: 'a1' } as never)
    expect(String((bash as { deny?: string }).deny)).toMatch(/factory run was stopped/)
  })

  test('the .catch fallback guards forbidden calls but not non-forbidden ones (fail-open for Read/Bash)', async ($, on) => {
    // The .catch at line 1441-1443 checks forbiddenOf(e) for spawned agents.
    // A forbidden call (push) is denied. A non-forbidden call (Read, Bash) is
    // allowed through — the .catch handler returns next(e), which is fail-open.
    //
    // This test documents the INTENDED design: the .catch is a last-resort guard
    // for forbidden operations. It is NOT a full stopped-agent guard.
    // If read($, stoppedAgents) were to throw, the stopped-agent check at line
    // 1413 would be skipped, and the .catch would only catch forbidden ops.
    on('tool.call', { tool: 'Bash' }, () => ({ result: 'ran' }) as never)
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    // Agent a2 (builder) is a spawned agent. Test the guard's behavior on it:
    // Forbidden call → denied:
    const push = await $.tool.call({ tool: 'Bash', command: 'git push origin HEAD', agentId: 'a2' } as never)
    expect(String((push as { deny?: string }).deny)).toMatch(/don't do this/)
    // Non-forbidden call → allowed (no deny, reaches the fallback handler above):
    const npm = await $.tool.call({ tool: 'Bash', command: 'npm test', agentId: 'a2' } as never)
    expect((npm as { deny?: string }).deny).toBeFalsy()
  })

  test('policy documentation: the guard has two separate concerns that can diverge under store failure', async ($, on) => {
    // Concern 1 (forbidden ops): guarded by .catch fallback — fails closed.
    // Concern 2 (stopped agents): guarded by read($, stoppedAgents) at line 1413 — no .catch.
    //
    // Under a store failure: Concern 1 works (push denied), Concern 2 doesn't
    // (stopped agent's Read/Bash proceeds).
    //
    // This test verifies that BOTH concerns work under normal conditions (no store failure):
    const w = engine(on)
    await startRun($)
    await answer($, 'a1', SPEC_ANSWER)
    await command($, 'plan-approved')
    // Stop the run — now a2 (builder) is in stoppedAgents.
    await command($, 'stop')
    // Concern 1: forbidden call from stopped agent — denied
    const push = await $.tool.call({ tool: 'Bash', command: 'git push origin HEAD', agentId: 'a2' } as never)
    expect(String((push as { deny?: string }).deny)).toMatch(/don't do this|factory run was stopped/)
    // Concern 2: non-forbidden call from stopped agent — denied (via stoppedAgents check)
    const read = await $.tool.call({ tool: 'Read', file_path: '/repo/a.ts', agentId: 'a2' } as never)
    expect(String((read as { deny?: string }).deny)).toMatch(/factory run was stopped/)
  })
})
