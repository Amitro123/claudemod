import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ChecksIO, DetectedChecks } from './checks'
import type { Blocked, Check, Extra, Finding, Outcome, Phase, Reviewer, Role, Run } from '../types'
import type { DoctorItem } from './flow'
import { buildRound, DIAGRAM, diagramSvg, pipelineLines } from './art'
import type { Theme } from './art'
import {
  approvePrompt,
  BUDGET_STOP,
  budgetDeny,
  budgetLine,
  buildPrompt,
  cleanFeature,
  detectProjectChecks,
  NOTHING_RAN,
  detectSetup,
  isLive,
  statusOf,
  waitsOnYou,
  activityText,
  isQuiet,
  progressBar,
  progressOf,
  statusReport,
  neverCommit,
  newRun,
  openFindings,
  parseDecision,
  parseTasks,
  parseVerdict,
  planPrompt,
  prPrompt,
  prRepoOf,
  reviewPrompt,
  extrasFrom,
  isExtra,
  LENSES,
  MAX_EXTRAS,
  reviewOf,
  reviewerLabel,
  skepticPrompt,
  ROLE_PROMPTS,
  ROLES,
  slugOf,
  titleOf,
  specPrompt,
  splitChecks,
  tailOf,
  rootOf,
  tok,
  tokensOf,
  untrackedOf,
  couldNotStart,
  ranChecks,
  leftOut,
  historyArgs,
  historyLeaks,
  stagedAddsArgs,
  waitsOnPerson,
  modelOf,
  modelsFor,
  parseSize,
  parseSkills,
  skillsLine,
  builtinSkill,
  lastLines,
  ledgerOf,
  OUTCOMES,
  outcomesLine,
  statsReport,
  newReview,
  reviewDonePrompt,
  doctorReport,
  nextActionsOf,
  nextActionsText,
  forbidsPush,
  parseBuilderTests,
  summaryOf,
  isLimitError,
  progressNote,
  resumePrompt,
} from './flow'
import { intakeNote, intakePrompt, parseIntake, reviewPlan, ROUTED_MODELS, touchesUi } from './intake'
import { acceptComment, answeredSince, askComment, escalateComment, issueFeature, issueFile, LABEL, NEEDS_HUMAN_LABEL, NEEDS_INFO_LABEL, parseQueue, parseRestIssue, parseRestIssueList, queueLines, queueText, refusal, rejectComment } from './issues'
import type { Issue, Queue, QueueState } from './issues'
import { addUsage, costOf, DEFAULT_CONFIG, parseConfig, protectedHits, usd } from './config'
import type { FactoryConfig } from './config'
import { applyRulings, changedOf, diffLines, disputable, forbiddenCommand, forbiddenInReview, forbiddenTool, routeReview } from './route'
import { FACTORY_START_TOOL, factoryArgs, type GoalTask, parseFactoryArgs, parsePlanApprovedArgs, parsePlanOutcome, parsePlanResultArgs, toolText } from './texts'

// Every run of the session, by slug, in the order they started: up to `concurrency` at work at once.
const runs = atom({ plugin: 'factory', key: 'runs' } as const, {} as Record<string, Run>)
// How many runs may work at once (the concurrency option). A run that waits on the person holds no slot.
let concurrency = 3
const KEEP_ENDED = 20

// Which run a step acts on: its slug, `rid`, passed beside $ through every step (the hooks compiler
// lets $ only be passed on, never wrapped). An empty rid (a command with no run named) means the run
// the person most likely means: one that waits on them, else the newest live one, else the newest.
export function pickRun(all: Record<string, Run>): Run | null {
  const list = Object.values(all).reverse()
  return list.find(r => isLive(r.phase) && waitsOnYou(r)) ?? list.find(r => isLive(r.phase)) ?? list[0] ?? null
}
async function getRun($: EngineInterface, rid: string): Promise<Run | null> {
  const all = await read($, runs)
  return rid ? (all[rid] ?? null) : pickRun(all)
}
// A new run joins the others; of the ended ones only the latest are kept. Its rid.
async function addRun($: EngineInterface, r: Run): Promise<string> {
  await update($, runs, all => {
    const ended = Object.values(all).filter(x => !isLive(x.phase))
    const drop = new Set(ended.slice(0, Math.max(0, ended.length - KEEP_ENDED)).map(x => x.slug))
    return { ...Object.fromEntries(Object.entries(all).filter(([k]) => !drop.has(k) && k !== r.slug)), [r.slug]: r }
  })
  return r.slug
}
// The run an agent belongs to.
async function agentRun($: EngineInterface, agentId: string): Promise<Run | null> {
  return Object.values(await read($, runs)).find(r => !!r.agents[agentId]) ?? null
}
// Runs at work: live and not waiting on the person. Each holds a slot.
const working = (all: Record<string, Run>) => Object.values(all).filter(r => isLive(r.phase) && !waitsOnYou(r))
// A command's run: named by a trailing @<slug> or @#<issue>, else the one pickRun finds.
async function targetOf($: EngineInterface, arg: string): Promise<{ rid: string; rest: string; error?: string }> {
  const m = /\s*@(#?)([\w.-]+)$/.exec(arg)
  const all = await read($, runs)
  if (!m) return { rid: pickRun(all)?.slug ?? '', rest: arg }
  const list = Object.values(all)
  const r = m[1] ? list.filter(x => x.issue === Number(m[2])).at(-1) : list.find(x => x.slug === m[2])
  if (!r) return { rid: '', rest: arg.slice(0, m.index), error: `No factory run ${m[1] ? `for issue #${m[2]}` : `named ${m[2]}`}: /factory status lists them.` }
  return { rid: r.slug, rest: arg.slice(0, m.index) }
}

const frame = atom({ plugin: 'factory', key: 'frame' } as const, 0)
const theme = atom({ plugin: 'factory', key: 'theme' } as const, 'dark' as Theme)
// The time, kept while a check runs, so the band and the pane count its seconds.
const now = atom({ plugin: 'factory', key: 'now' } as const, 0)
// The agents of runs that were stopped, newest last: their tool calls stay refused after a new run starts.
const stoppedAgents = atom({ plugin: 'factory', key: 'stoppedAgents' } as const, [] as string[])
const MAX_STOPPED = 50

const PANE = 'factory'
const PANE_TITLE = 'Factory'
const PLAN_TOOL = 'mcp__goal-run__plan'
const MAX_CHECK_ROUNDS = 2
const MAX_SLUG_TRIES = 5
// How long one check may run before it counts as timed out (the checkTimeout option, in minutes).
let checkTimeoutMs = 600_000
const FRAME_MS = 700
const ACCENT = '#2563eb'
const START_TOOL = FACTORY_START_TOOL
const STATUS_TOOL = 'mcp__factory__status'
const REVIEW_TOOL = 'mcp__factory__review'
const CONTROL_TOOL = 'mcp__factory__control'
const FROM_CONVERSATION = `Start a factory run on the work this conversation is about: call ${START_TOOL} with the feature (what to build, in a short paragraph, naming the file, issue or to-do item it comes from; a to-do item's id as followupId). If there is no such work yet, ask me what the factory should build. Don't do the work yourself.`
const STARTED_NOTE = "The factory does the work from here: don't start it yourself or propose a plan. Tell the person in one line, and that its plan comes up for their approval."
const STOPPED_DENY = 'The factory run was stopped. Stop now and answer with one line.'

// Set from the options when the module registers.
let maxRounds = 2
let checksOption = ''
let setupOption = ''
let autoPr = false
let modelsOption: 'auto' | 'fixed' = 'auto'
let skillsOption: Partial<Record<Role, string[]>> = {}
// The intake before the spec, and the review route by its risk and surfaces (the intake option).
let intakeOn = true
// Once the approver approves, the PR is merged as soon as it is open (the autoMerge option).
let autoMerge = false

// The run's API-equivalent cost so far, for the band and the pane: nothing until a priced model ran.
const costTag = (r: Run) => {
  const c = r.usage ? costOf(r.usage, r.prices ?? DEFAULT_CONFIG.prices).usd : 0
  return c > 0 ? ` · ${usd(c)}` : ''
}

// The repository's .factory/config.json, read from the main checkout: a branch can't change it.
async function configOf($: EngineInterface, root: string): Promise<FactoryConfig> {
  return parseConfig(await $.fs.read(`${root}/.factory/config.json`).then(t => String(t), () => null))
}
// A role's skills: the option's for it, else the factory's own.
// The skeptic has no skill of the factory's own: only one the skills option names.
const skillsOf = (role: Role) => skillsOption[role] ?? (role === 'skeptic' || role === 'extra' ? [] : [builtinSkill(role)])
// Whether a skeptic tries to refute the round's blocker and major findings before the builder goes back.
let skepticOn = true
// A run's name in a line: an issue's as #<n> and its title, without the pointer to its file.
const runTitle = (r: Run, n: number) =>
  r.issue ? `#${r.issue} ${titleOf(r.feature.replace(/^GitHub issue #\d+: /, '').replace(/\. The request is the issue's text in [\s\S]*$/, ''), n)}` : titleOf(r.feature, n)

// goal-run's answer to a plan: for the run whose plan waits there (the newest, if several do).
async function planRun($: EngineInterface): Promise<string> {
  return Object.values(await read($, runs)).filter(x => x.phase === 'plan').at(-1)?.slug ?? ''
}

// One queue per run: a run's transitions happen in order, while another run's checks or agents go on.
const queues = new Map<string, Promise<void>>()
const timers: { cancel: () => void }[] = []

function serial($: EngineInterface, rid: string, job: () => Promise<void>): Promise<void> {
  const key = rid || '*'
  const next = (queues.get(key) ?? Promise.resolve()).then(job, job).catch(() => {})
  queues.set(key, next)
  return next
}

// A move to another phase stamps when it began; a stop to wait keeps where the progress stood.
// A run that is no longer live (stopped, done) never moves to another phase: a step that awaited
// something (git, a route, a record) while the person pressed Stop must not undo the Stop.
// A move refused that way returns null, not the unchanged run: every caller treats null as "stop
// here", so none of them sends a prompt or starts an agent for a stopped run (the 2026-11-14
// inspection found onSpec, finishReview, the spec retry and the review retry doing so).
async function patch($: EngineInterface, rid: string, fn: (r: Run) => Run): Promise<Run | null> {
  const t = await $.clock.now()
  let refused = false
  let out: Run | null = null
  await update($, runs, all => {
    const key = rid || pickRun(all)?.slug
    const cur = key ? all[key] : undefined
    if (!key || !cur) return all
    let next = fn(cur)
    if (next.phase !== cur.phase) {
      if (!isLive(cur.phase)) {
        refused = true
        next = cur
      } else {
        const held = next.phase === 'needs-human' || next.phase === 'stopped' ? { lastProgress: progressOf(cur) } : {}
        next = { ...next, ...held, phaseSince: t }
      }
    }
    out = next
    return next === cur ? all : { ...all, [key]: next }
  })
  return refused ? null : out
}

// A move to a phase the run works in clears what it was blocked on.
const moveTo = (r: Run, phase: Phase, note: string): Run => ({ ...r, phase, note, blocked: null, checking: null, isAskingChecks: false })

async function block($: EngineInterface, rid: string, blocked: Blocked, note: string, fn: (r: Run) => Run = r => r) {
  // A run stopped meanwhile stays stopped.
  await patch($, rid, r => (isLive(r.phase) ? { ...fn(r), phase: 'needs-human', blocked, note, checking: null, isAskingChecks: false } : r))
}

async function git($: EngineInterface, args: string[], cwd?: string) {
  return $.process.run(['git', ...args], { ...(cwd ? { cwd } : {}), timeoutMs: 60_000 }).catch(err => ({ exitCode: 1, stdout: '', stderr: String(err) }))
}

// A command that couldn't start (its program isn't installed) says so: `notStarted`. process.run
// rejects for that and for a timeout. An exit code the process returned is its own, 127 included:
// a script (npm, make) passes on the 127 of a command missing inside it, which is a failure.
// A run that failed at the time limit timed out, however the engine reports it (a rejection naming the
// timeout, or the killed process's exit).
async function run$($: EngineInterface, argv: string[], cwd: string) {
  const t0 = await $.clock.now()
  const atLimit = async () => (await $.clock.now()) - t0 >= checkTimeoutMs - 1_000
  return $.process.run(argv, { cwd, timeoutMs: checkTimeoutMs }).then(
    async out => ({ ...out, notStarted: false, timedOut: out.exitCode !== 0 && (await atLimit()) }),
    async err => {
      const timedOut = !couldNotStart(err) || (await atLimit())
      return { exitCode: 1, stdout: '', stderr: String(err), notStarted: !timedOut, timedOut }
    },
  )
}

const describe = (role: Role, r: Run) =>
  role === 'intake' ? 'intake' : role === 'builder' ? `builder, round ${buildRound(r)}` : role === 'spec' ? 'spec-writer' : role === 'approver' ? 'approver' : role === 'skeptic' ? 'skeptic' : `${ROLES[role].label} review`

// Whether goal-run's command is registered now, asked fresh each time (mods start in no set order).
// Inlined, not hasCommand from ./runtime: some CLI releases' hooks compiler follows $ only into a
// function declared in the same file, and a module that fails that rule does not load at all
// (seen with CLI 2.1.286; 2.1.312, which CI pins, allows it).
const goalRunThere = async ($: EngineInterface) => (await $.command.list().catch(() => [])).some(c => c.name === 'session-goal')

// Starts one role's agent in the run's worktree. A role type the engine refused to register falls
// back to a general-purpose agent carrying the role's instructions in its prompt.
// Each agent's spawn, by id: what a retry needs (the reload of the module forgets them; the step
// then waits for Retry instead).
const spawns = new Map<string, { role: Role; prompt: string; hasModel: boolean; isRetry: boolean; asked?: string; review?: string; agentType?: string }>()
// The models each agent of the run actually ran its requests on (from each step's usage): the
// record shows them beside the model asked for, so a rewrite on the way (a router) shows after the fact.
const ranOn = new Map<string, Set<string>>()

// `review`: the extra reviewer this agent is (its name), and `agentType` the session's agent that runs it.
// `model`: the model the review route gave this reviewer (a routed ux or ui-design review).
async function spawnRole($: EngineInterface, rid: string, role: Role, prompt: string, { onSessionModel = false, review = '', agentType = '', model = '' } = {}): Promise<boolean> {
  const r = await getRun($, rid)
  if (!r || !isLive(r.phase)) return false
  const spec = ROLES[role]
  const label = review ? `${review} review` : describe(role, r)
  const job = prompt
  // A builder started on a worktree that already has work: told what is there, from git.
  if (role === 'builder') {
    const [log, status] = await Promise.all([git($, ['log', '--oneline', `${r.base}..HEAD`], r.worktree), git($, ['status', '--porcelain', '-uall'], r.worktree)])
    const note = progressNote(log.exitCode === 0 ? log.stdout : '', status.exitCode === 0 ? status.stdout : '', [r.specFile])
    if (note) prompt = `${note}\n\n${prompt}`
  }
  const skills = skillsOf(role)
  if (skills.length) prompt = `${skillsLine(skills)}\n\n${prompt}`
  const budget = (await configOf($, rootOf(r)).catch(() => DEFAULT_CONFIG)).budgets[role] ?? 0
  if (budget > 0) prompt = `${prompt}\n\n${budgetLine(budget)}`
  // An agent of the session's own runs on its own model.
  const asked = model || modelOf(r, role)
  const base = { prompt, description: `factory · ${label}`, ...(onSessionModel || agentType ? {} : { model: asked }), cwd: r.worktree }
  let res = await $.agent.spawn({ ...base, subagentType: agentType || `factory:${spec.name}` }).catch(err => ({ deny: String(err) }) as { deny: string })
  if ('deny' in res && res.deny) {
    res = await $.agent.spawn({ ...base, subagentType: 'general-purpose', prompt: `${ROLE_PROMPTS[role]}\n\n${prompt}` }).catch(err => ({ deny: String(err) }) as { deny: string })
  }
  if ('deny' in res && res.deny) {
    await block($, rid, { on: 'start', role }, `Could not start the ${label}: ${res.deny}`)
    return false
  }
  // Without an id in the answer, the agent is found in the session's list by its description.
  // Not one another run already follows: two runs' builders share a description.
  const known = new Set(Object.values(await read($, runs)).flatMap(x => Object.keys(x.agents)))
  const id = (res as { agentId?: string }).agentId ?? (await $.agent.list().catch(() => [])).filter(a => a.description === base.description && !known.has(a.id)).at(-1)?.id
  if (!id) {
    await block($, rid, { on: 'start', role }, `Started the ${label}, but can't follow it: no agent id.`)
    return false
  }
  const t0 = await $.clock.now()
  await patch($, rid, cur => ({
    ...cur,
    agents: { ...cur.agents, [id]: role },
    ...(budget > 0 ? { agentBudgets: { ...cur.agentBudgets, [id]: budget } } : {}),
    activity: { role, text: 'starting', at: t0, calls: 0 },
    ...(role === 'builder' ? { builderId: id, stats: bump(cur, s => ({ ...s, builderStarts: s.builderStarts + 1 })).stats } : {}),
    reviews: cur.reviews.map(x => (x.role === (review || role) ? { ...x, agentId: id } : x)),
  }))
  spawns.set(id, { role, prompt: job, hasModel: !onSessionModel && !agentType, isRetry: onSessionModel, asked: onSessionModel ? 'the session model' : agentType ? `${agentType}'s own` : asked, review, agentType })
  return true
}

// What a run agent's tool call would do that is never its job (push, publish, deploy, delete outside
// the worktree), or ''. A command that can't be checked counts as one: the guard fails closed.
function forbiddenOf(e: { tool: string }): string {
  try {
    return forbiddenTool(e.tool) || (e.tool === 'Bash' || e.tool === 'PowerShell' ? forbiddenCommand(String((e as unknown as { command?: unknown }).command ?? '')) : '')
  } catch (err) {
    return `a command the factory couldn't check (${String(err).slice(0, 80)})`
  }
}
const forbiddenDeny = (what: string) =>
  `The factory's agents don't do this (${what}): the work stays on the run's branch in its worktree, and the person opens the PR once it is approved. Leave it out and go on.`

// Why an agent's turn ended without its answer: what the step's note says, '' when it answered.
export function whyEnded(e: { reason: string; answer: string; refusal?: { explanation: string | null } }): string {
  if (e.reason === 'answer') return ''
  if (e.reason === 'aborted') return 'it was interrupted'
  if (e.reason === 'refusal') return `the model refused${e.refusal?.explanation ? `: ${e.refusal.explanation}` : ''}`
  const said = e.answer.trim()
  return `an API error ended it${said ? `: ${tailOf(said, 1)}` : ''}`
}

// What a run needs before it can start, checked cheaply: no run going, a git repository with a commit.
async function preflight($: EngineInterface): Promise<{ root: string; head: string } | { error: string }> {
  const busy = working(await read($, runs))
  if (busy.length >= concurrency) return { error: `${busy.length} factory run${busy.length === 1 ? ' is' : 's are'} already working (the concurrency option allows ${concurrency}): ${busy.map(x => titleOf(x.feature, 50)).join('; ')}. /factory stop @<run> ends one.` }
  const top = await git($, ['rev-parse', '--show-toplevel'], await $.session.root())
  if (top.exitCode !== 0) return { error: 'The factory needs a git repository: it builds on a branch, in a worktree of its own.' }
  const root = top.stdout.trim()
  const head = await git($, ['rev-parse', 'HEAD'], root)
  if (head.exitCode !== 0) return { error: 'The repository has no commit yet to build from.' }
  return { root, head: head.stdout.trim() }
}

type StartOpts = { issue?: number; intakeAnswers?: string[]; issueAnyway?: boolean }
async function start($: EngineInterface, args: string, extras: Extra[] = [], opts: StartOpts = {}): Promise<string> {
  const parsed = parseFactoryArgs(args)
  const feature = cleanFeature(parsed.feature)
  const followupId = parsed.followupId
  if (!feature) return 'What should the factory build? /factory <feature>'
  const ready = await preflight($)
  if ('error' in ready) return ready.error
  const { root, head } = ready
  const at = await $.clock.now()
  const slug = slugOf(feature)
  let r: Run | null = null
  // A branch or folder name already taken gets a number; any other failure is reported as it is.
  for (let k = 1; k <= MAX_SLUG_TRIES && !r; k++) {
    const next = newRun(feature, at, head, root, k === 1 ? slug : `${slug}-${k}`)
    const added = await git($, ['worktree', 'add', '-b', next.branch, next.worktree, next.base], root)
    if (added.exitCode === 0) r = next
    else if (!/already exists/i.test(added.stderr)) return `Could not create a worktree for the run: ${tailOf(added.stderr, 3)}`
  }
  if (!r) return `Could not create a worktree for the run: the branches factory/${slug} to factory/${slug}-${MAX_SLUG_TRIES} are all taken.`
  // The branch the checkout is on: the PR goes into it. A detached HEAD names none.
  const onBranch = await git($, ['rev-parse', '--abbrev-ref', 'HEAD'], root)
  const baseRef = onBranch.exitCode === 0 && onBranch.stdout.trim() !== 'HEAD' ? onBranch.stdout.trim() : ''
  // The GitHub repositories the PR can go to, read once: the PR prompt is built from them without a wait.
  const remotes = { origin: await remoteSlug($, root, 'origin'), upstream: await remoteSlug($, root, 'upstream') }
  const created: Run = {
    ...r,
    remotes,
    gate: (await goalRunThere($)) ? 'goal-run' : 'factory',
    ...(followupId ? { followupId } : {}),
    ...(baseRef ? { baseRef } : {}),
    ...(opts.issue ? { issue: opts.issue, ...(opts.issueAnyway ? { issueAnyway: true } : {}) } : {}),
    ...(opts.intakeAnswers?.length ? { intakeAnswers: opts.intakeAnswers } : {}),
    ...(extras.length ? { extras, reviews: [...r.reviews, ...extras.map(e => reviewOf(e.name))] } : {}),
    // With the intake, it runs first; the spec waits for its ACCEPT. The roles run on the routed models.
    ...(intakeOn ? { phase: 'intake' as const, note: 'the intake is weighing the feature', steps: { ...r.steps, spec: { state: 'wait' as const, tokens: 0 } }, models: { ...ROUTED_MODELS } } : {}),
  }
  await keepOutOfGit($, root)
  await readTheme($)
  const cfg = await configOf($, root)
  created.prices = cfg.prices
  const rid = await addRun($, created)
  await ensureTicking($)
  void $.ui.open({ id: PANE, title: PANE_TITLE })
  if (intakeOn) {
    await serial($, rid, async () => void (await spawnRole($, rid, 'intake', intakePrompt(created))))
    return `Factory run started: ${titleOf(created.feature, 120)}. Branch ${created.branch}, worktree ${created.worktree}; the intake (${modelOf(created, 'intake')}) decides whether to build it, at what scope and risk, before the spec.`
  }
  await serial($, rid, async () => void (await spawnRole($, rid, 'spec', specPrompt(created))))
  return `Factory run started: ${titleOf(created.feature, 120)}. Branch ${created.branch}, worktree ${created.worktree}; the spec-writer is writing ${created.specFile}.`
}

// The worktrees live in .factory/ of the repository: listed in its exclude file, found through
// git (a .git that is a file, in a worktree or a submodule, has it elsewhere), never committed.
async function keepOutOfGit($: EngineInterface, root: string) {
  const found = await git($, ['rev-parse', '--git-path', 'info/exclude'], root)
  if (found.exitCode !== 0 || !found.stdout.trim()) return
  const rel = found.stdout.trim()
  const path = /^([a-zA-Z]:)?[\\/]/.test(rel) ? rel : `${root}/${rel}`
  const text = await $.fs.read(path).then(t => String(t), () => '')
  if (/^\.factory\/$/m.test(text)) return
  await $.fs.write(path, `${text}${text && !text.endsWith('\n') ? '\n' : ''}.factory/\n`).catch(() => {})
}

// The diagram's palette follows the theme set in /config; dark when it can't be read.
async function readTheme($: EngineInterface) {
  const row = (await $.config.list().catch(() => [])).find(r => r.key === 'theme')
  const value = String((row as { value?: unknown } | undefined)?.value ?? '')
  await update($, theme, () => (/light/i.test(value) ? 'light' : 'dark'))
}

async function startIntake($: EngineInterface, rid: string) {
  const r = await patch($, rid, cur => moveTo(cur, 'intake', 'the intake is weighing the feature'))
  if (r?.phase === 'intake') await spawnRole($, rid, 'intake', intakePrompt(r))
}

// The intake's judgment: ACCEPT goes on to the spec within the scope it accepted; NEEDS-INFO and
// REJECT stop for the person (answer it, build it anyway, or stop). An intake that decided nothing
// (stopped, or no INTAKE line) waits for a Retry: nothing goes past it unweighed.
async function onIntake($: EngineInterface, rid: string, answer: string, why: string) {
  if (why) return block($, rid, { on: 'start', role: 'intake' }, `The intake stopped before deciding: ${why}. Retry runs it again.`)
  const intake = parseIntake(answer)
  if (!intake) {
    await patch($, rid, cur => bump(cur, s => ({ ...s, formatMisses: [...s.formatMisses, 'intake: no INTAKE line'].slice(-12) })))
    return block($, rid, { on: 'start', role: 'intake' }, 'The intake gave no INTAKE line. Retry runs it again.')
  }
  const cur0 = await patch($, rid, cur => ({ ...cur, intake }))
  // An issue's run: the intake's answer goes on the issue. A question or a rejection parks the issue
  // and frees the factory for the next one, unless the operator ran it anyway.
  if (cur0?.issue && !cur0.issueAnyway && intake.verdict !== 'ACCEPT') {
    const parked = intake.verdict === 'NEEDS-INFO'
    const root = rootOf(cur0)
    await ghComment($, root, cur0.issue, parked ? askComment(intake.reason, intake.questions) : rejectComment(intake.reason))
    if (parked) await ghLabel($, root, cur0.issue, NEEDS_INFO_LABEL, true)
    await setQueue($, root, cur0.issue, parked ? 'needs-info' : 'rejected', intake.reason)
    await record($, rid, 'intake on the issue', `${intake.verdict}: ${intake.reason}${intake.questions.length ? `\n${intake.questions.map(q => `- ${q}`).join('\n')}` : ''}`)
    await patch($, rid, cur => moveTo(cur, 'stopped', parked ? `parked: #${cur0.issue} waits on its author` : `#${cur0.issue} rejected by the intake`))
    await recordStats($, rid)
    $.ui.toast(parked ? `Factory: asked the author of #${cur0.issue}; it waits for their reply` : `Factory: the intake rejected #${cur0.issue} (said why on the issue)`)
    return nextIssue($)
  }
  if (cur0?.issue && intake.verdict === 'ACCEPT') await ghComment($, rootOf(cur0), cur0.issue, acceptComment(intake.scope, intake.risk, intake.surfaces))
  if (intake.verdict !== 'ACCEPT') {
    await block($, rid, { on: 'intake' }, intakeNote(intake))
    $.ui.toast(intake.verdict === 'REJECT' ? 'The factory intake rejected the feature: /factory approve builds it anyway' : 'The factory intake needs your answers: /factory rework <answers>')
    return
  }
  await respec($, rid)
}

async function onSpec($: EngineInterface, rid: string, answer: string, why: string) {
  const tasks = why ? [] : parseTasks(answer)
  if (!tasks.length) {
    await block($, rid, { on: 'spec' }, why ? `The spec-writer stopped: ${why}.` : 'The spec-writer gave no TASKS list.', r => ({ ...r, steps: { ...r.steps, spec: { ...r.steps.spec, state: 'fail' } } }))
    return
  }
  // goal-run is asked again: installed or removed since the run started, the plan goes where it can.
  const viaGoalRun = (await getRun($, rid))?.gate === 'goal-run' && (await goalRunThere($))
  const size = parseSize(answer)
  const r = await patch($, rid, cur => ({
    ...moveTo(cur, 'plan', 'waiting for you to approve the plan'),
    tasks,
    ...(size ? { size } : {}),
    // A routed run keeps the models the intake's route gave it; otherwise the size decides.
    models: cur.intake ? { ...cur.models } : { ...modelsFor(size, modelsOption), spec: modelOf(cur, 'spec') },
    gate: viaGoalRun ? 'goal-run' : 'factory',
    steps: { ...cur.steps, spec: { ...cur.steps.spec, state: 'pass' } },
  }))
  if (r && viaGoalRun) void $.prompt.submit({ text: planPrompt(r) }).catch(() => {})
  else if (r) void askPlan($, rid)
}

// The PR, put to the person in the conversation once the approver approved or escalated: what was
// built and why, with Open (or Approve anyway), Not now, or what to change under Other (a rework).
const OPEN_PR = 'Open the PR'
const APPROVE_ANYWAY = 'Approve the PR anyway'
async function askPr($: EngineInterface, rid: string) {
  const r = await getRun($, rid)
  const escalated = r?.phase === 'needs-human' && r.blocked?.on === 'escalate'
  if (!r || (r.phase !== 'ready' && !escalated)) return
  const yes = escalated ? APPROVE_ANYWAY : OPEN_PR
  const lines = [
    `The factory's change for "${titleOf(r.feature, 120)}" ${escalated ? 'was escalated by the approver' : 'was approved'}: ${r.note}`,
    ...(r.stat || r.summary ? [`Changed: ${[r.stat, r.summary].filter(Boolean).join(' · ')}`] : []),
    `Branch ${r.branch}${r.recorded ? `; what each step said is in ${r.record}/` : ''}.`,
    '',
    `${escalated ? 'Approve it anyway' : 'Open the PR'}? To send it back to the builder, say what to change under Other.`,
  ]
  let answer = ''
  try {
    answer = await $.ui.ask(lines.join('\n'), { header: 'Factory PR', options: [yes, NOT_NOW] })
  } catch {
    return
  }
  const now = await getRun($, rid)
  if (!now || now.phase !== r.phase) return
  if (answer === yes) return void (await approveNow($, rid))
  if (answer && answer !== NOT_NOW) return void (await reworkNow($, rid, answer))
}

// Without goal-run's dialog, the plan is put to the person in the engine's own: in the main
// conversation, not only in the band. "Other" carries what to change.
const APPROVE_PLAN = 'Approve and build'
const NOT_NOW = 'Not now'
async function askPlan($: EngineInterface, rid: string) {
  const r = await getRun($, rid)
  if (!r || r.phase !== 'plan' || r.gate !== 'factory') return
  const tasks = r.tasks.map((t, i) => `${i + 1}. [${t.priority}] ${t.title}`).join('\n')
  let answer = ''
  try {
    answer = await $.ui.ask(`The factory's plan for "${titleOf(r.feature, 120)}"${r.size ? ` (${r.size})` : ''}, spec in ${r.specFile}:\n${tasks}\n\nReviewers: ${r.reviews.map(x => reviewerLabel(x.role)).join(', ')}.\n\nApprove it, and the builder starts? To change it, say what under Other.`, { header: 'Factory plan', options: [APPROVE_PLAN, NOT_NOW] })
  } catch {
    return
  }
  // Answered in the band meanwhile, or stopped: nothing left to decide here.
  if ((await getRun($, rid))?.phase !== 'plan') return
  if (answer === APPROVE_PLAN) return void serial($, rid, () => onPlan($, rid, { approved: true }))
  if (answer && answer !== NOT_NOW) return void serial($, rid, () => respec($, rid, answer))
}

async function onPlan($: EngineInterface, rid: string, outcome: { approved: true; goalTasks?: GoalTask[] } | { changes: string } | { kept: true }) {
  const r = await getRun($, rid)
  if (!r || r.phase !== 'plan') return
  if ('approved' in outcome) {
    if (outcome.goalTasks) await patch($, rid, cur => ({ ...cur, goalTasks: outcome.goalTasks }))
    return startBuild($, rid, [], [])
  }
  // The person has a goal of their own in goal-run: the factory's band asks instead.
  if ('kept' in outcome) {
    // Heard twice (the hook and goal-run's command): the factory's own question is asked once.
    if (r.gate === 'factory') return
    await patch($, rid, cur => ({ ...cur, gate: 'factory', note: 'waiting for you to approve the plan (here: goal-run keeps your own goal)' }))
    return void askPlan($, rid)
  }
  await respec($, rid, outcome.changes || 'The person asked for changes to the plan.')
}

async function respec($: EngineInterface, rid: string, feedback = '') {
  const r = await patch($, rid, cur => ({ ...moveTo(cur, 'spec', feedback ? 'revising the spec' : 'writing the spec'), steps: { ...cur.steps, spec: { ...cur.steps.spec, state: 'run' } } }))
  if (r) await spawnRole($, rid, 'spec', specPrompt(r, feedback))
}

async function startBuild($: EngineInterface, rid: string, findings: Finding[], failed: Check[], said = '', resume = '') {
  const note = resume ? 'the builder carries on' : said ? 'reworking it as you asked' : failed.length ? 'fixing the checks' : findings.length ? `fixing ${findings.length} finding${findings.length === 1 ? '' : 's'}` : 'building'
  const r = await patch($, rid, cur => ({ ...moveTo(cur, 'build', note), steps: { ...cur.steps, builder: { ...cur.steps.builder, state: 'run' } } }))
  if (!r || r.phase !== 'build') return
  // A later round goes back to the builder that built it: it keeps what it read and why, and its
  // prompt cache. A message it can't take (gone, refused) starts a new builder with the whole job.
  if (r.builderId) {
    // A builder that stopped mid-job carries on; one that finished a round gets the next.
    const prompt = resume ? resumePrompt(resume) : buildPrompt(r, findings, failed, { again: true, note: said })
    const sent = await $.session.send({ to: { agentId: r.builderId }, text: prompt }).then(x => x.isDelivered, () => false)
    if (sent) {
      const before = spawns.get(r.builderId)
      spawns.set(r.builderId, { role: 'builder', prompt: buildPrompt(r, findings, failed, { note: said }), hasModel: before?.hasModel ?? true, isRetry: false })
      return
    }
  }
  await spawnRole($, rid, 'builder', buildPrompt(r, findings, failed, { note: said }))
}

// What the builder left uncommitted is committed by the factory: reviewers and the PR see the same
// commits. Tracked changes all go in; a new file only when it isn't installed dependencies, build
// output or a credential (those are left out, and the run's note says so).
async function onBuilt($: EngineInterface, rid: string) {
  const r = await getRun($, rid)
  if (!r) return
  const status = await git($, ['status', '--porcelain', '-z', '-uall'], r.worktree)
  if (status.exitCode === 0 && status.stdout.trim()) {
    const untracked = untrackedOf(status.stdout)
    const bySetup = new Set(r.setupFiles ?? [])
    const skipped = leftOut(untracked.filter(p => neverCommit(p) || bySetup.has(p)))
    const fresh = untracked.filter(p => !neverCommit(p) && !bySetup.has(p))
    let out = await git($, ['add', '-u'], r.worktree)
    if (out.exitCode === 0 && fresh.length) out = await git($, ['add', '--', ...fresh], r.worktree)
    // A new file the builder staged itself (git add .env) is in the index, not untracked: unstaged too.
    const added = out.exitCode === 0 ? await git($, stagedAddsArgs, r.worktree) : null
    const sneaked = added?.exitCode === 0 ? added.stdout.split('\0').filter(p => p && neverCommit(p)) : []
    if (sneaked.length) {
      out = await git($, ['reset', '-q', '--', ...sneaked], r.worktree)
      skipped.push(...leftOut(sneaked).filter(p => !skipped.includes(p)))
    }
    const staged = out.exitCode === 0 ? await git($, ['diff', '--cached', '--quiet'], r.worktree) : out
    if (out.exitCode === 0 && staged.exitCode !== 0) out = await git($, ['commit', '-m', `factory: ${titleOf(r.feature, 64)}`, ...(titleOf(r.feature, 64) !== r.feature.trim() ? ['-m', r.feature.trim()] : [])], r.worktree)
    if (out.exitCode !== 0) {
      await block($, rid, { on: 'builder' }, `The builder's work could not be committed: ${tailOf(`${out.stdout}\n${out.stderr}`, 2)}`)
      return
    }
    if (skipped.length) await patch($, rid, cur => ({ ...cur, skipped }))
  }
  if (!(await baseHolds($, rid))) return
  // The base may have just moved (the person named the branch the work is on).
  const base = (await getRun($, rid))?.base ?? r.base
  // What the builder committed itself never went through the filter above. Every commit since the
  // base is pushed, so one it added and later deleted or renamed counts too.
  const history = await git($, historyArgs(base), r.worktree)
  let leaked: ReturnType<typeof historyLeaks> = []
  try {
    if (history.exitCode !== 0) throw new Error(tailOf(`${history.stdout}\n${history.stderr}`, 2))
    leaked = historyLeaks(history.stdout)
  } catch (err) {
    await block($, rid, { on: 'builder' }, `The factory could not read the branch's history for files the factory never commits: ${err instanceof Error ? err.message : String(err)}`)
    return
  }
  if (leaked.length) {
    await block($, rid, { on: 'builder' }, `The builder committed files the factory never commits: ${leaked.map(l => `${l.path} (in ${l.commits.map(c => c.slice(0, 7)).join(', ')})`).join(', ')}. Take them out of the branch's history, then retry.`)
    return
  }
  const stat = await git($, ['diff', '--stat', base, 'HEAD'], r.worktree)
  if (stat.exitCode === 0 && stat.stdout.trim()) {
    await patch($, rid, cur => ({ ...cur, stat: lastLines(stat.stdout, 1) }))
    await record($, rid, `changes after builder round ${r.round + 1}`, stat.stdout)
  }
  await runChecks($, rid)
}

// The run compares the branch with its base: the reviewers' diff, the approver's file list, the PR. A
// builder that checked out another branch's history (a PR to build on, say) leaves the branch no longer
// starting from that base, and every comparison counts the whole other tree. The person says which
// branch the work is on top of: one the branch contains is offered, or any other under Other.
const NOT_NOW_BASE = 'Not now'
const mmss = (ms: number) => `${Math.floor(ms / 60_000)}:${String(Math.floor((ms % 60_000) / 1000)).padStart(2, '0')}`
async function baseHolds($: EngineInterface, rid: string): Promise<boolean> {
  const r = await getRun($, rid)
  if (!r) return false
  const holds = await git($, ['merge-base', '--is-ancestor', r.base, 'HEAD'], r.worktree)
  // 1: not an ancestor. Anything else (git couldn't tell) isn't held against the run.
  if (holds.exitCode !== 1) return true
  const refs = await git($, ['for-each-ref', '--merged', 'HEAD', '--sort=-committerdate', '--format=%(refname:short)', 'refs/heads', 'refs/remotes'], r.worktree)
  const offered = (refs.exitCode === 0 ? refs.stdout.split('\n') : []).map(x => x.trim()).filter(x => x && x !== r.branch && !x.endsWith('/HEAD') && x !== 'HEAD').slice(0, 3)
  let answer = ''
  try {
    answer = await $.ui.ask(
      `The builder's branch ${r.branch} no longer starts from ${r.baseRef || r.base.slice(0, 12)}: its history was replaced, likely by a checkout of another branch to build on. Compared with ${r.baseRef || 'that commit'}, the change would count that branch's whole tree. Which branch is the work on top of? The reviewers, the approver and the PR compare with it.`,
      { header: 'Factory base', options: [...offered, NOT_NOW_BASE] },
    )
  } catch {
    answer = ''
  }
  if (answer.trim() && answer !== NOT_NOW_BASE && (await setBase($, rid, answer.trim())) === '') return true
  await block($, rid, { on: 'base' }, `The branch no longer starts from ${r.baseRef || r.base.slice(0, 12)}: say which branch the work is on top of with /factory base <branch>, or Retry to be asked again.`)
  return false
}

// Moves the run's base to a branch or commit the work is on top of: '' when it did, else why not.
async function setBase($: EngineInterface, rid: string, ref: string): Promise<string> {
  const r = await getRun($, rid)
  if (!r) return 'No factory run.'
  const sha = await git($, ['rev-parse', '--verify', '--quiet', `${ref}^{commit}`], r.worktree)
  if (sha.exitCode !== 0 || !sha.stdout.trim()) return `No branch or commit "${ref}" in the run's repository.`
  const under = await git($, ['merge-base', '--is-ancestor', sha.stdout.trim(), 'HEAD'], r.worktree)
  if (under.exitCode !== 0) return `${ref} isn't under the run's branch ${r.branch}: the work isn't on top of it.`
  await patch($, rid, cur => ({ ...cur, base: sha.stdout.trim(), baseRef: ref }))
  await record($, rid, 'base', `The run's base moved to ${ref} (${sha.stdout.trim()}).`)
  return ''
}

async function namesIn($: EngineInterface, dir: string) {
  return (await $.fs.list(dir).catch(() => [])).map(f => f.name)
}

// The engine's files, as check detection reads them.
const checksIO = ($: EngineInterface): ChecksIO => ({
  list: async dir => (await $.fs.list(dir).catch(() => [])).map(f => ({ name: f.name, isDir: String((f as { kind?: string }).kind) === 'dir' || String((f as { kind?: string }).kind) === 'directory' })),
  read: path => $.fs.read(path).then(t => String(t), () => null),
})

// The checks of this run: the option, else the project's checks file, else what detection finds in the
// worktree and the commands in the spec's acceptance criteria. Never throws; says why when it finds none.
async function checkCommands($: EngineInterface, r: Run): Promise<DetectedChecks> {
  try {
    const diff = await git($, ['diff', '--name-only', ...spanOf(r)], r.worktree)
    const touched = [...(diff.exitCode === 0 ? diff.stdout.split(/\r?\n/).map(l => l.trim()).filter(Boolean) : []), ...(r.untracked ?? [])]
    const specPath = /^([A-Za-z]:|\/)/.test(r.specFile) ? r.specFile : `${r.worktree}/${r.specFile}`
    const spec = checksOption.trim() || r.kind === 'review' ? null : await $.fs.read(specPath).then(t => String(t), () => null)
    const io: ChecksIO = {
      list: async dir => (await $.fs.list(dir).catch(() => [])).map(f => ({ name: f.name, isDir: String((f as { kind?: string }).kind) === 'dir' || String((f as { kind?: string }).kind) === 'directory' })),
      read: path => $.fs.read(path).then(t => String(t), () => null),
    }
    // The person's checks file sits in the main repository; .factory/ is git-excluded, so a worktree
    // never has it, and one the builder writes there must not count.
    const checksFile = await $.fs.read(`${r.kind === 'review' ? r.worktree : rootOf(r)}/.factory/checks.json`).then(t => String(t), () => null)
    return await detectProjectChecks(io, r.worktree, { explicit: checksOption, touched, spec, checksFile })
  } catch (e) {
    return { checks: [], warnings: [String(e)], sources: {}, reason: `${NOTHING_RAN} Warning: ${String(e).slice(0, 120)}` }
  }
}

// A fresh worktree has no dependencies installed: the `setup` option, or the lockfile's install, runs
// once a run before its first checks. Its failure is the person's to look at, not the builder's.
async function setUp($: EngineInterface, rid: string, r: Run, files: string[]): Promise<boolean> {
  // A review runs in the person's own checkout: nothing is installed there.
  if (r.setupDone || r.kind === 'review') return true
  // What was untracked before the install: whatever it adds beside (a lockfile npm install writes
  // where there was none) is the setup's, not the change's, and never goes into its commits.
  const before = await git($, ['status', '--porcelain', '-z', '-uall'], r.worktree)
  const had = new Set(before.exitCode === 0 ? untrackedOf(before.stdout) : [])
  const cmds = setupOption.trim() ? splitChecks(setupOption) : [detectSetup(files)].filter((c): c is string[] => c !== null)
  for (const [k, argv] of cmds.entries()) {
    if (!(await stillIn($, rid, 'checks'))) return false
    await nowRunning($, rid, argv, k, cmds.length, true)
    const out = await runOrSkip($, rid, argv, r.worktree)
    if (out.isSkipped) {
      await record($, rid, 'setup', `Skipped by the person: ${argv.join(' ')}`)
      continue
    }
    if (out.exitCode !== 0) {
      const check: Check = { cmd: argv.join(' '), ok: false, tail: tailOf(`${out.stdout}\n${out.stderr}`) }
      await block($, rid, { on: 'setup' }, `The setup failed: ${check.cmd}. Fix it (or set the setup option), then Retry.`, cur => ({ ...cur, checks: [check], steps: { ...cur.steps, checks: { ...cur.steps.checks, state: 'fail' } } }))
      return false
    }
  }
  const after = await git($, ['status', '--porcelain', '-z', '-uall'], r.worktree)
  const made = after.exitCode === 0 ? untrackedOf(after.stdout).filter(p => !had.has(p) && !neverCommit(p)) : []
  await patch($, rid, cur => ({ ...cur, setupDone: true, checking: null, ...(made.length ? { setupFiles: made.slice(0, 50) } : {}) }))
  return true
}

// The files that decide what an auto-detected command does: its scripts, its install, its test hooks.
// Detection looks at the root, one level down and the touched folders, so each file is matched at any
// depth (`**/` takes the root too). The project's own .factory/checks.json is untracked in a worktree:
// a change to its commands changes the commands themselves, which asks again.
const CHECK_CONFIGS = [
  '.factory/checks.json',
  ...[
    'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', '.npmrc', '.pnpmfile.cjs',
    'pyproject.toml', 'setup.cfg', 'setup.py', 'pytest.ini', 'tox.ini', 'noxfile.py', 'conftest.py',
    'Makefile', 'makefile', 'GNUmakefile', 'go.mod', 'Cargo.toml',
    'pom.xml', 'build.gradle', 'build.gradle.kts', 'settings.gradle', 'settings.gradle.kts', 'gradle.properties',
    '*.sln', '*.csproj', '*.fsproj', 'Directory.Build.props', 'Directory.Build.targets',
    'jest.config.*', 'vitest.config.*', 'babel.config.*',
  ].map(f => `:(glob)**/${f}`),
]
const RUN_THEM = 'Run them'

// Commands the factory found itself run outside the session's permission prompts, in a worktree the
// builder just wrote: the person lets them run first, and again whenever the files that define them
// change. Commands set in the checks and setup options are the person's own and aren't asked about.
async function approveAuto($: EngineInterface, rid: string, r: Run, cmds: string[][], orGoOn = false): Promise<boolean> {
  const last = await git($, ['log', '-1', '--format=%H', 'HEAD', '--', ...CHECK_CONFIGS], r.worktree)
  const key = `${cmds.map(c => c.join(' ')).join('; ')} @ ${last.stdout.trim()}`
  if (r.autoApproved === key) return true
  const changed = await git($, ['diff', '--name-only', r.base, 'HEAD', '--', ...CHECK_CONFIGS], r.worktree)
  const touched = changed.exitCode === 0 ? changed.stdout.trim().split('\n').filter(Boolean) : []
  const question = [
    `Before the factory runs the checks it found in the project, in ${r.worktree}:`,
    ...cmds.map(c => `$ ${c.join(' ')}`),
    ...(touched.length ? ['', `The builder changed what these run: ${touched.join(', ')}. Look at that diff before you let them run.`] : []),
    '',
    "They run the code the builder wrote, its tests and config included, outside your permission prompts, and in every later round of this run with whatever the builder changes, until the files that define them change. Run them? (The checks and setup options set them for good.)",
  ].join('\n')
  let answer = ''
  // Asked inside the run's serial queue, so nothing else of the run moves until it's answered: during
  // the checks no agent of the run is working, so nothing waits on it.
  // The run waits on the person meanwhile: the band says so, in the color of a run waiting for them.
  await patch($, rid, cur => ({ ...cur, note: 'waiting for your OK to run the checks (a question in the conversation)', isAskingChecks: true }))
  try {
    answer = await $.ui.ask(question, { header: 'Factory checks', options: [RUN_THEM, NOT_NOW] })
  } catch {
    answer = ''
  }
  await patch($, rid, cur => ({ ...cur, isAskingChecks: false, note: 'running the checks' }))
  if (answer === RUN_THEM) {
    await patch($, rid, cur => ({ ...cur, autoApproved: key, askedChecks: undefined }))
    return true
  }
  if (orGoOn) return false
  await block($, rid, { on: 'checks' }, `The checks wait for your OK to run what the factory found: ${cmds.map(c => c.join(' ')).join('; ')}. /factory checks-ok runs them, Retry asks again, or set the checks and setup options.`, cur => ({ ...cur, askedChecks: key, steps: { ...cur.steps, checks: { ...cur.steps.checks, state: 'wait' } } }))
  return false
}

// Ends the wait on the command running now, when the person lets the run go on without it. The process
// itself can't be killed from here: it runs out under its time limit, and its result is ignored.
// The check each run is waiting on now, to let it go on without it: by run.
const skippers = new Map<string, () => void>()
const SKIPPED = { exitCode: -1, stdout: '', stderr: '', notStarted: false, timedOut: false, isSkipped: true }
async function runOrSkip($: EngineInterface, rid: string, argv: string[], cwd: string) {
  const skipped = new Promise<typeof SKIPPED>(resolve => void skippers.set(rid, () => resolve(SKIPPED)))
  try {
    return await Promise.race([run$($, argv, cwd).then(out => ({ ...out, isSkipped: false })), skipped])
  } finally {
    skippers.delete(rid)
  }
}

// The command starting now, for the band and the pane: a long one reads as running, with its seconds.
async function nowRunning($: EngineInterface, rid: string, argv: string[], k: number, total: number, isSetup = false) {
  const t = await $.clock.now()
  await update($, now, () => t)
  await patch($, rid, cur => ({ ...cur, note: `${isSetup ? 'installing' : 'running the checks'}: ${argv.join(' ')}`, checking: { cmd: argv.join(' '), index: k + 1, total, since: t, ...(isSetup ? { isSetup } : {}) } }))
}

async function stillIn($: EngineInterface, rid: string, phase: Run['phase']) {
  return (await getRun($, rid))?.phase === phase
}

async function runChecks($: EngineInterface, rid: string) {
  const r = await patch($, rid, cur => ({
    ...moveTo(cur, 'checks', 'running the checks'),
    steps: { ...cur.steps, builder: cur.kind === 'review' ? cur.steps.builder : { ...cur.steps.builder, state: 'pass' }, checks: { ...cur.steps.checks, state: 'run' } },
    checkRound: cur.kind === 'review' ? 0 : cur.checkRound + 1,
  }))
  if (!r || r.phase !== 'checks') return
  const files = await namesIn($, r.worktree)
  const found = await checkCommands($, r)
  const auto = [
    ...(!r.setupDone && !setupOption.trim() && r.kind !== 'review' ? [detectSetup(files)].filter((c): c is string[] => c !== null) : []),
    ...(!checksOption.trim() ? found.checks : []),
  ]
  if (auto.length && !(await approveAuto($, rid, r, auto, r.kind === 'review'))) {
    if (r.kind !== 'review') return
    // A review whose checks the person didn't let run goes on without them: the reviewers are told.
    await patch($, rid, cur => ({ ...cur, checks: [], checksNote: `The person didn't let the found commands run (${auto.map(c => c.join(' ')).join('; ')}), so no check ran.`, checking: null, steps: { ...cur.steps, checks: { ...cur.steps.checks, state: 'skip' } } }))
    return startReviews($, rid)
  }
  if (!(await setUp($, rid, r, files))) return
  const cmds = found.checks
  await patch($, rid, cur => ({ ...cur, note: 'running the checks' }))
  const results: Check[] = []
  for (const [k, argv] of cmds.entries()) {
    // A Stop meanwhile ends the checks here: the rest don't run for nothing.
    if (!(await stillIn($, rid, 'checks'))) return
    await nowRunning($, rid, argv, k, cmds.length)
    const out = await runOrSkip($, rid, argv, r.worktree)
    if (out.isSkipped) {
      results.push({ cmd: argv.join(' '), ok: false, tail: '', isMissing: true, isSkipped: true })
      continue
    }
    // pytest that found no tests (exit 5), or a python without pytest: nothing ran, so nothing failed.
    const said = `${out.stdout}\n${out.stderr}`
    if (argv.includes('pytest') && (out.exitCode === 5 || /No module named pytest/.test(said))) {
      results.push({ cmd: argv.join(' '), ok: false, tail: '', isMissing: true, why: out.exitCode === 5 ? 'no tests collected' : 'pytest is not installed' })
      continue
    }
    results.push({ cmd: argv.join(' '), ok: out.exitCode === 0, tail: out.exitCode === 0 ? '' : tailOf(`${out.stdout}\n${out.stderr}`), ...(out.notStarted ? { isMissing: true } : {}), ...(out.timedOut ? { isTimedOut: true } : {}) })
  }
  // The repository's protected paths: a branch that modified or deleted one fails the checks, and
  // the builder is sent back with the list. Only a run's branch: a review changes nothing.
  if (r.kind !== 'review') {
    const patterns = (await configOf($, rootOf(r))).protectedPaths
    const names = patterns.length ? await git($, ['diff', '--name-status', '-z', r.base, 'HEAD'], r.worktree) : null
    const hits = names ? (names.exitCode === 0 ? protectedHits(names.stdout, patterns) : [`git could not list the branch's changes: ${tailOf(names.stderr, 1)}`]) : []
    if (hits.length) results.unshift({ cmd: 'protected paths', ok: false, tail: `The branch changed files the repository protects (.factory/config.json protected_paths); undo these changes:\n${hits.join('\n')}` })
  }
  const timedOut = results.filter(c => c.isTimedOut)
  const failed = results.filter(c => !c.ok && !c.isMissing)
  const missing = results.filter(c => c.isMissing)
  const ran = results.filter(c => !c.isMissing)
  if (results.length) await record($, rid, 'checks', results.map(c => `${c.isSkipped ? '– (skipped by the person)' : c.why ? `– (${c.why})` : c.isMissing ? '– (not installed)' : c.isTimedOut ? `⏱ (timed out after ${mmss(checkTimeoutMs)})` : c.ok ? '✓' : '✗'} ${c.cmd}${c.tail ? `\n${c.tail}` : ''}`).join('\n'))
  // Why nothing ran, or what detection warned about, or which programs aren't installed: the
  // reviewers and the approver read it.
  const notes = [
    ...(missing.some(c => c.isSkipped) ? [`Skipped by the person, so not run: ${missing.filter(c => c.isSkipped).map(c => c.cmd).join(', ')}.`] : []),
    ...(missing.some(c => !c.isSkipped && !c.why) ? [`Not installed here, so not run: ${missing.filter(c => !c.isSkipped && !c.why).map(c => c.cmd).join(', ')}.`] : []),
    ...(missing.some(c => c.why) ? [`Not run: ${missing.filter(c => c.why).map(c => `${c.cmd} (${c.why})`).join(', ')}.`] : []),
    ...(!ran.length ? [found.reason || NOTHING_RAN] : []),
    ...(ran.length && found.warnings.length ? [found.warnings.join('; ')] : []),
  ]
  const checksNote = notes.join(' ')
  if (!cmds.length) await record($, rid, 'checks', checksNote || NOTHING_RAN)
  const after = await patch($, rid, cur => ({ ...cur, checks: results, checksNote, checking: null, steps: { ...cur.steps, checks: { ...cur.steps.checks, state: !ran.length ? 'skip' : failed.length ? 'fail' : 'pass' } } }))
  if (!after || after.phase !== 'checks') return
  // A check that ran out of time says nothing about the code: slow, hung or waiting on something. The
  // builder isn't sent to fix it; the person looks.
  if (timedOut.length) {
    return block($, rid, { on: 'checks' }, `${timedOut.map(c => c.cmd).join(', ')} didn't finish in ${mmss(checkTimeoutMs)}. It may be slow or hung: run it yourself in ${r.worktree}, then Retry. A suite that needs longer than that is run as narrower commands with the checks option.`)
  }
  // A review has no builder: failing checks are for the reviewers, and for Claude after them.
  if (!failed.length || after.kind === 'review') return startReviews($, rid)
  if (after.checkRound < MAX_CHECK_ROUNDS) return startBuild($, rid, [], failed)
  await block($, rid, { on: 'checks' }, `The checks still fail after ${after.checkRound} builder passes: ${failed.map(c => c.cmd).join(', ')}.`)
}

// Every reviewer looks at every round: a fix for one reviewer is new code for the others too.
// What the diff calls for: the files and lines it changed, read with git; unreadable, the deepest review.
async function routeOf($: EngineInterface, r: Run) {
  const names = await git($, ['diff', '--name-status', '-z', ...spanOf(r)], r.worktree)
  const diff = await git($, ['diff', '-U0', ...spanOf(r)], r.worktree)
  const readable = names.exitCode === 0 && diff.exitCode === 0 && diff.stdout.length < 5_000_000
  const changed = names.exitCode === 0 ? changedOf(names.stdout) : []
  return { ...routeReview(changed, readable ? diffLines(diff.stdout) : [], readable), uiTouched: touchesUi(changed) }
}

async function startReviews($: EngineInterface, rid: string) {
  const before = await getRun($, rid)
  const found = before ? await routeOf($, before) : null
  const route = found ? { deep: found.deep, focus: found.focus } : null
  // With the intake's risk and surfaces: which reviewers run this round, and on which models.
  const plan = before?.intake && route ? reviewPlan(before.intake, route, found!.uiTouched, await configOf($, rootOf(before))) : null
  if (route?.focus.length || plan) await record($, rid, `review route, round ${(before?.round ?? 0) + 1}`, [...(plan ? plan.why.map(w => `- ${w}`) : route?.deep ? ['Deep review (the code reviewer on opus too).'] : []), ...(route?.focus ?? []).map(f => `- ${f}`)].join('\n'))
  const r = await patch($, rid, cur => {
    const round = cur.round + 1
    // The UI reviewers the route adds, once: they stay for later rounds (a fix is new code for them too).
    const uiExtras = (plan?.extras ?? []).filter(u => !cur.extras?.some(e => e.name === u.name)).map(u => ({ name: u.name, focus: u.focus, model: u.model, routed: true }))
    const extras = [...(cur.extras ?? []), ...uiExtras]
    const reviews = [...cur.reviews, ...uiExtras.map(e => reviewOf(e.name))]
    // A reviewer the route leaves out this round is skipped, not run: the security review without a
    // security surface. Rules only add review, so one that ran in an earlier round runs again.
    const skip = (role: string) => !!plan && role === 'security' && !plan.security && !cur.reviews.some(x => x.role === 'security' && x.round > 0 && x.state !== 'skip')
    const securityModel = plan?.security ?? (cur.reviews.some(x => x.role === 'security' && x.round > 0 && x.state !== 'skip') ? modelOf(cur, 'security') : null)
    return {
      ...moveTo(cur, 'review', `reviewing, round ${round}`),
      round,
      ...(route ? { route } : {}),
      models: plan ? { ...cur.models, code: plan.codeModel, ...(securityModel ? { security: securityModel } : {}) } : route?.deep ? { ...cur.models, code: 'opus' } : cur.models,
      ...(uiExtras.length ? { extras } : {}),
      checkRound: 0,
      reviews: reviews.map(x => ({ ...x, state: skip(x.role) ? 'skip' : 'run', findings: [], round, agentId: null, understood: undefined, notChecked: undefined })),
    }
  })
  if (r?.phase === 'review') await spawnReviewers($, rid, r)
}

// A review of the person's checkout: did the checkout change after the reviewers read it? The diff they read
// is in the record; a different diff now means someone edited while they worked. No saved diff: unknown, false.
async function reviewedDiffChanged($: EngineInterface, r: Run): Promise<boolean> {
  if (!r.diffFile) return false
  const before = await $.fs.read(r.diffFile).then(t => String(t), () => null)
  const now = await git($, ['diff', ...spanOf(r)], r.worktree)
  return before !== null && now.exitCode === 0 && now.stdout !== before
}

// The reviewers of this round not started yet (all of them, or those a failed start left).
// What a run's diff spans: its branch's commits since the base, or, for a review of the person's
// checkout, the working tree against the base (uncommitted work included).
const spanOf = (r: Run) => (r.kind === 'review' ? [r.base] : [r.base, 'HEAD'])

async function spawnReviewers($: EngineInterface, rid: string, r: Run) {
  const stat = await git($, ['diff', '--stat', ...spanOf(r)], r.worktree)
  // The whole diff in a file the reviewers Read: their own git is refused with no one to approve it.
  const diff = r.record ? await git($, ['diff', ...spanOf(r)], r.worktree) : null
  if (diff && diff.exitCode === 0 && diff.stdout.trim()) {
    const file = `${r.record}/diff-round-${r.round}.patch`
    if (await $.fs.write(file, diff.stdout).then(() => true, () => false)) r = (await patch($, rid, cur => ({ ...cur, diffFile: file }))) ?? r
  }
  for (const x of r.reviews.filter(v => v.round === r.round && v.state === 'run' && !v.agentId)) {
    const prompt = reviewPrompt(r, x.role, stat.exitCode === 0 ? stat.stdout.trim() : '')
    const extra = r.extras?.find(e => e.name === x.role)
    const ok = isExtra(x.role) ? await spawnRole($, rid, 'extra', prompt, { review: x.role, agentType: extra?.agent ?? '', model: extra?.model ?? '' }) : await spawnRole($, rid, x.role as Role, prompt)
    if (!ok) return
  }
}

async function onReview($: EngineInterface, rid: string, role: Reviewer, agentId: string, answer: string, why: string) {
  const verdict = !why ? parseVerdict(answer) : { state: 'fail' as const, findings: [{ severity: 'major' as const, where: '-', text: `The reviewer stopped: ${why}.` }] }
  const missed = why ? [] : [...(!/VERDICT:/i.test(answer) ? ['VERDICT'] : []), ...(!('understood' in verdict && verdict.understood) ? ['UNDERSTOOD'] : []), ...(!('notChecked' in verdict && verdict.notChecked) ? ['NOT CHECKED'] : [])]
  const r = await patch($, rid, cur => {
    const next = { ...cur, reviews: cur.reviews.map(x => (x.agentId === agentId ? { ...x, state: verdict.state, findings: verdict.findings, understood: 'understood' in verdict ? verdict.understood : undefined, notChecked: 'notChecked' in verdict ? verdict.notChecked : undefined } : x)) }
    return missed.length ? bump(next, s => ({ ...s, formatMisses: [...s.formatMisses, `${role} review (round ${cur.round}): no ${missed.join(', ')}`].slice(-12) })) : next
  })
  if (!r || r.phase !== 'review') return
  const mine = r.reviews.filter(x => x.round === r.round)
  if (mine.some(x => x.state === 'run')) return
  // A reviewer that ended without a verdict (an API error, say) didn't review: the run waits for a
  // Retry rather than sending the builder after a "finding" that isn't one, or the approver ahead.
  const failed = mine.find(x => x.state === 'fail')
  if (failed) return block($, rid, { on: 'start', role: failed.role }, `${failed.findings[0]?.text ?? 'The reviewer stopped.'} The ${failed.role} review didn't run; Retry runs it again.`)
  const changes = mine.filter(x => x.state === 'changes')
  // A review run has no builder round to save: its skeptic weighs every finding, minor ones too,
  // since a false positive there costs the person's time all the same.
  if (r.kind === 'review' && !mine.some(x => x.findings.length)) return finishReview($, rid)
  if (r.kind !== 'review' && (!changes.length || r.round >= maxRounds)) return startApprover($, rid)
  // Before the builder goes back over the blocker and major findings, a skeptic tries to refute them:
  // a round spent on a finding that isn't real costs a whole builder pass.
  const disputed = r.kind === 'review' ? mine.flatMap(x => x.findings.map(finding => ({ role: x.role, finding }))) : changes.flatMap(x => disputable(x.findings).map(finding => ({ role: x.role, finding })))
  if (!skepticOn || !disputed.length) return r.kind === 'review' ? finishReview($, rid) : startBuild($, rid, openFindings(changes), [])
  const onSecurity = disputed.some(x => x.role === 'security')
  const changedSinceReview = r.kind === 'review' && (await reviewedDiffChanged($, r))
  const next = await patch($, rid, cur => ({ ...cur, disputed, changedSinceReview, note: `a skeptic checks ${disputed.length} finding${disputed.length === 1 ? '' : 's'}`, models: { ...cur.models, skeptic: onSecurity ? 'opus' : 'sonnet' } }))
  if (next && !(await spawnRole($, rid, 'skeptic', skepticPrompt(next, disputed)))) {
    // No skeptic could start: the findings go to the builder as they are. Only from the stop that
    // failed start made: a run stopped meanwhile (spawnRole refuses a run that isn't live) stays stopped.
    const back = await patch($, rid, cur => (cur.phase === 'needs-human' && cur.blocked?.on === 'start' && cur.blocked.role === 'skeptic' ? { ...cur, phase: 'review', blocked: null } : cur))
    if (back?.phase !== 'review') return
    return r.kind === 'review' ? finishReview($, rid) : startBuild($, rid, openFindings(changes), [])
  }
}

// The skeptic's rulings: a refuted finding is dropped and a downgraded one is minor, each with its
// evidence in the record; what stands goes to the builder. Nothing standing: the approver decides.
// A skeptic that ended without its answer refutes nothing: the findings go as they are.
async function onSkeptic($: EngineInterface, rid: string, answer: string, why: string) {
  const r = await getRun($, rid)
  if (!r) return
  const disputed = r.disputed ?? []
  const { dropped } = why ? { dropped: [] } : applyRulings(disputed.map(x => x.finding), answer, f => disputed.some(x => x.finding === f && x.role === 'security'))
  // A ruling is matched to its finding by role, where and text, and each match takes one: two
  // findings alike (the same one twice from a reviewer, or from two) each get their own ruling,
  // not the first one's. A dropped finding whose disputed entry can't be found (state that crossed
  // a serialization, say) is kept for the record under the reviewer it best matches.
  const queue = new Map<string, Array<(typeof dropped)[number]>>()
  const roleOf = (d: (typeof dropped)[number]): Reviewer =>
    disputed.find(y => y.finding === d.finding)?.role
    ?? disputed.find(y => y.finding.where === d.finding.where && y.finding.text === d.finding.text)?.role
    ?? 'code'
  for (const d of dropped) {
    const role = roleOf(d)
    const key = `${role}\0${d.finding.where}\0${d.finding.text}`
    const list = queue.get(key) ?? []
    list.push(d)
    queue.set(key, list)
  }
  const after = await patch($, rid, cur => ({
    ...cur,
    disputed: [],
    refuted: [...(cur.refuted ?? []), ...dropped.map(d => ({ role: roleOf(d), finding: d.finding, ruling: d.ruling, why: d.why }))],
    reviews: cur.reviews.map(x => {
      if (x.round !== cur.round || (x.state !== 'changes' && cur.kind !== 'review')) return x
      const findings = x.findings.flatMap(f => {
        const d = queue.get(`${x.role}\0${f.where}\0${f.text}`)?.shift()
        return !d ? [f] : d.ruling === 'downgraded' ? [{ ...f, severity: 'minor' as const }] : []
      })
      return { ...x, findings, state: x.state === 'changes' && findings.some(f => f.severity !== 'minor') ? x.state : x.state === 'changes' ? 'pass' : x.state }
    }),
  }))
  if (dropped.length) await record($, rid, 'skeptic rulings', dropped.map(d => `${d.ruling.toUpperCase()}: [${d.finding.severity}] ${d.finding.where} ${d.finding.text}\n  ${d.why}`).join('\n'))
  if (!after || after.phase !== 'review') return
  if (after.kind === 'review') return finishReview($, rid)
  const changes = after.reviews.filter(x => x.round === after.round && x.state === 'changes')
  if (changes.length) return startBuild($, rid, openFindings(changes), [])
  await startApprover($, rid)
}

async function startApprover($: EngineInterface, rid: string) {
  const r = await patch($, rid, cur => ({ ...moveTo(cur, 'approve', 'the approver is deciding'), steps: { ...cur.steps, approver: { ...cur.steps.approver, state: 'run' } } }))
  if (!r || r.phase !== 'approve') return
  const stat = await git($, ['diff', '--stat', r.base, 'HEAD'], r.worktree)
  await spawnRole($, rid, 'approver', approvePrompt(r, stat.exitCode === 0 ? stat.stdout.trim() : ''))
}

async function onApprover($: EngineInterface, rid: string, answer: string, why: string) {
  // An approver that ended without a decision decided nothing: Retry, not an escalation to approve past.
  if (why) return block($, rid, { on: 'start', role: 'approver' }, `The approver stopped before deciding: ${why}. Retry runs it again.`, r => ({ ...r, steps: { ...r.steps, approver: { ...r.steps.approver, state: 'fail' } } }))
  const parsed = parseDecision(answer)
  if (parsed.decision === null) return block($, rid, { on: 'start', role: 'approver' }, `${parsed.reason} Retry runs it again.`, r => ({ ...r, steps: { ...r.steps, approver: { ...r.steps.approver, state: 'fail' } } }))
  // With no check run, nothing was verified by running it: an APPROVE becomes the person's call
  // (Approve PR anyway is their override).
  const r0 = await getRun($, rid)
  const unverified = parsed.decision === 'APPROVE' && r0 !== null && !ranChecks(r0).length
  // The builder said its own test run failed (L2): an APPROVE over that is the person's call too.
  const failingTests = parsed.decision === 'APPROVE' && !unverified && !!r0?.builderTests?.failing
  const decision = unverified || failingTests ? 'ESCALATE' : parsed.decision
  const reason = unverified
    ? `The approver would approve${parsed.reason ? ` (${parsed.reason})` : ''}, but no check ran, so nothing was verified by running it. Approve the PR anyway if the reviews are enough, or set the checks option.`
    : failingTests
      ? `The approver would approve${parsed.reason ? ` (${parsed.reason})` : ''}, but the builder reported failing tests: ${r0!.builderTests!.text}. Approve the PR anyway if they aren't the change's, or send it back with /factory rework.`
      : parsed.reason
  if (decision === 'ESCALATE') {
    await block($, rid, { on: 'escalate' }, reason, r => ({ ...r, steps: { ...r.steps, approver: { ...r.steps.approver, state: 'changes' } } }))
    await recordStats($, rid)
    if (r0?.issue) {
      await ghComment($, rootOf(r0), r0.issue, escalateComment(reason))
      await ghLabel($, rootOf(r0), r0.issue, NEEDS_HUMAN_LABEL, true)
      await setQueue($, rootOf(r0), r0.issue, 'needs-human', reason)
      // Waiting on the person holds no slot: the next issue can start meanwhile.
      await nextIssue($)
    }
    $.ui.toast('The factory needs you: Approve PR, /factory rework <what to change>, or /factory stop')
    void askPr($, rid)
    return
  }
  // The approver is an agent: the PR, outward-facing, waits for the person unless autoPr is on.
  if (autoPr) return finish($, rid, reason, true)
  const ready = await patch($, rid, r => ({ ...moveTo(r, 'ready', `approved${reason ? `: ${reason}` : ''}. Open the PR when you're ready`), steps: { ...r.steps, approver: { ...r.steps.approver, state: 'pass' } } }))
  if (ready?.phase !== 'ready') return
  $.ui.toast('The approver approved the change: Open PR in the factory band, /factory approve, or /factory rework <what to change>')
  void askPr($, rid)
}

// A review run is done: its findings (what the skeptic left standing) go to the main Claude to fix.
async function finishReview($: EngineInterface, rid: string) {
  const r = await patch($, rid, cur => {
    const n = cur.reviews.reduce((k, x) => k + x.findings.filter(f => f.severity !== 'minor').length, 0)
    return { ...moveTo(cur, 'done', n ? `reviewed: ${n} finding${n === 1 ? '' : 's'} to fix, sent to Claude` : 'reviewed: no blocker or major finding'), ledger: ledgerOf(cur) }
  })
  if (!r) return
  await record($, rid, 'review findings', reviewDonePrompt(r))
  await recordStats($, rid)
  void $.prompt.submit({ text: reviewDonePrompt(r) }).catch(() => $.ui.toast(`The review is done: ${r.note}. /factory status lists the findings.`))
}

// The base a review compares the checkout with: the one named, else where the branch left the
// repository's default branch (or its upstream); on that branch itself, the last commit, so only
// uncommitted work is reviewed.
async function reviewBase($: EngineInterface, root: string, named: string): Promise<{ base: string; ref: string } | { error: string }> {
  if (named) {
    const v = await git($, ['rev-parse', '--verify', '--quiet', `${named}^{commit}`], root)
    return v.exitCode === 0 ? { base: v.stdout.trim(), ref: named } : { error: `No commit or branch named ${named}.` }
  }
  const head = (await git($, ['rev-parse', 'HEAD'], root)).stdout.trim()
  for (const ref of ['@{upstream}', 'origin/HEAD', 'origin/main', 'origin/master', 'main', 'master']) {
    const mb = await git($, ['merge-base', 'HEAD', ref], root)
    const at = mb.stdout.trim()
    if (mb.exitCode === 0 && at && at !== head) return { base: at, ref: ref === '@{upstream}' ? 'the upstream' : ref }
  }
  return { base: head, ref: 'HEAD' }
}

// /factory review [base=<ref>] [what the change is for]: the reviewers alone, on the checkout's change.
async function startReview($: EngineInterface, focus: string, named = '', extras: Extra[] = []): Promise<string> {
  const ready = await preflight($)
  if ('error' in ready) return ready.error
  const { root } = ready
  const found = await reviewBase($, root, named.trim())
  if ('error' in found) return found.error
  const diff = await git($, ['diff', '--quiet', found.base], root)
  const others = await git($, ['ls-files', '--others', '--exclude-standard', '-z'], root)
  const untracked = others.exitCode === 0 ? others.stdout.split('\0').filter(p => p && !p.startsWith('.factory/') && !neverCommit(p)) : []
  if (diff.exitCode === 0 && !untracked.length) return `Nothing to review: the checkout has no change against ${found.ref}${found.ref === 'HEAD' ? ' (the last commit)' : ''}. /factory review base=<branch> names what to compare with.`
  const at = await $.clock.now()
  const feature = cleanFeature(focus) || 'the change in this checkout'
  const slug = `review-${slugOf(feature).slice(0, 30)}-${Math.floor(at / 1000).toString(36).slice(-5)}`
  // The project's test commands, for the reviewers (a review runs none): detection over what changed.
  const names = await git($, ['diff', '--name-only', found.base], root)
  const touched = [...(names.exitCode === 0 ? names.stdout.split('\n').map(l => l.trim()).filter(Boolean) : []), ...untracked]
  const tests = await detectProjectChecks(checksIO($), root, { explicit: checksOption, touched, spec: null, checksFile: await $.fs.read(`${root}/.factory/checks.json`).then(t => String(t), () => null) }).catch(() => null)
  const base = newReview(feature, at, found.base, root, slug, untracked)
  const created: Run = { ...base, baseRef: found.ref, ...(tests?.checks.length ? { testCommands: tests.checks.slice(0, 8).map(c => c.join(' ')) } : {}), ...(extras.length ? { extras, reviews: [...base.reviews, ...extras.map(e => ({ ...reviewOf(e.name), state: 'run' as const, round: 1 }))] } : {}) }
  await keepOutOfGit($, root)
  await readTheme($)
  const route = await routeOf($, created)
  const rid = await addRun($, { ...created, ...(route ? { route, ...(route.deep ? { models: { ...created.models, code: 'opus' } } : {}) } : {}) })
  await ensureTicking($)
  void $.ui.open({ id: PANE, title: PANE_TITLE })
  void serial($, rid, () => runChecks($, rid))
  return `Factory review started: ${created.reviews.map(x => reviewerLabel(x.role)).join(', ')} on the checkout against ${found.ref} (${found.base.slice(0, 12)})${untracked.length ? `, with ${untracked.length} new file${untracked.length === 1 ? '' : 's'}` : ''}. The checks it finds run first, once you let them; then the reviewers, whose findings come back to Claude.`
}

// The main Claude says what became of the review's findings: kept on the run, in its stats, and in
// the repository's .factory/findings.jsonl, where the status adds them up over every review.
async function reportOutcomes($: EngineInterface, rid: string, raw: unknown): Promise<string> {
  const r = await getRun($, rid)
  if (!r?.ledger?.length) return 'No review findings wait for their outcomes.'
  const given = (Array.isArray(raw) ? raw : []) as { id?: unknown; outcome?: unknown; why?: unknown }[]
  const known = new Set(r.ledger.map(x => x.id))
  const ok = given.filter(g => known.has(String(g.id ?? '').toUpperCase()) && OUTCOMES.includes(String(g.outcome ?? '') as Outcome))
  if (!ok.length) return `No outcome read: give outcomes as [{ id: "F1", outcome: "fixed" | "not-a-bug" | "wont-fix", why }], for ${[...known].join(', ')}.`
  const by = new Map(ok.map(g => [String(g.id).toUpperCase(), { outcome: String(g.outcome) as Outcome, why: String(g.why ?? '').trim().slice(0, 300) }]))
  const after = await patch($, rid, cur => ({ ...cur, ledger: (cur.ledger ?? []).map(x => (by.has(x.id) && !['refuted', 'downgraded'].includes(x.outcome ?? '') ? { ...x, ...by.get(x.id)!, ...(by.get(x.id)!.why ? {} : { why: undefined }) } : x)) }))
  if (!after?.ledger) return 'No review findings wait for their outcomes.'
  const at = new Date(await $.clock.now()).toISOString()
  const lines = after.ledger.filter(x => by.has(x.id)).map(x => JSON.stringify({ at, feature: titleOf(after.feature, 80), kind: after.kind ?? 'run', role: x.role, severity: x.severity, where: x.where, outcome: x.outcome, why: x.why ?? '' }))
  const file = `${after.kind === 'review' ? after.worktree : rootOf(after)}/.factory/findings.jsonl`
  const before = await $.fs.read(file).then(t => String(t), () => '')
  await $.fs.write(file, `${before}${before && !before.endsWith('\n') ? '\n' : ''}${lines.join('\n')}\n`).catch(() => {})
  await recordStats($, rid)
  const open = after.ledger.filter(x => !x.outcome).map(x => x.id)
  return `Recorded ${by.size} outcome${by.size === 1 ? '' : 's'}. ${outcomesLine(after.ledger)}${open.length ? ` Still to report: ${open.join(', ')}.` : ''}`
}

// Every outcome recorded in this repository, added up: what the status says of how far reviews hold.
async function repoOutcomes($: EngineInterface, root: string): Promise<string> {
  const text = await $.fs.read(`${root}/.factory/findings.jsonl`).then(t => String(t), () => '')
  const entries = text.split('\n').filter(Boolean).flatMap(l => {
    try {
      return [JSON.parse(l) as { outcome?: Outcome }]
    } catch {
      return []
    }
  })
  return entries.length ? `Review findings in this repository so far (.factory/findings.jsonl): ${outcomesLine(entries)}` : ''
}

// The main Claude opened the approved run's PR: it now reads as opened, with its link.
async function prOpened($: EngineInterface, rid: string, url: string): Promise<string> {
  const link = url.trim()
  if (!/^https?:\/\/\S+$/.test(link)) return 'pr-opened needs the PR\'s link as url.'
  const r = await getRun($, rid)
  if (!r || r.phase !== 'done') return 'No approved factory run waits for its PR.'
  await patch($, rid, cur => ({ ...cur, pr: { state: 'opened', url: link }, note: `PR opened: ${link}` }))
  if (r.issue) {
    await setQueue($, rootOf(r), r.issue, 'pr', '', link)
    await ghLabel($, rootOf(r), r.issue, NEEDS_HUMAN_LABEL, false)
    await nextIssue($)
  }
  return `Recorded: the factory run's PR is ${link}.${r.issue && draining ? ' The next issue starts.' : ''}`
}

// Approved by the person (or by the approver, with autoPr on): the main Claude opens the PR.
// The PR is only requested here (L3): it reads as opened once the main Claude reports its link (the
// control tool's pr-opened). A feature that says not to push gets the commands, for the person.
// Before the PR: the branch is synced with the latest base and the checks run again on it, since
// other work may have landed since the run was tested. Nothing to sync (no remote base, or it is
// already in the branch): straight on. A conflict, or a check that fails on the synced branch, stops
// the run for the person. `byApprover`: the approver approved (not the person over an escalation).
async function finish($: EngineInterface, rid: string, reason: string, byApprover = false) {
  const r0 = await getRun($, rid)
  if (!r0 || !isLive(r0.phase)) return
  if (r0.kind !== 'review' && !(await syncWithBase($, rid, r0))) return
  await openPr($, rid, reason, byApprover)
}

async function syncWithBase($: EngineInterface, rid: string, r: Run): Promise<boolean> {
  const base = prBaseOf(r)
  if (!base || forbidsPush(r.feature)) return true
  const remote = `origin/${base}`
  await git($, ['fetch', 'origin', base], r.worktree)
  const there = await git($, ['rev-parse', '--verify', '--quiet', `${remote}^{commit}`], r.worktree)
  if (there.exitCode !== 0 || !there.stdout.trim()) return true
  const tip = there.stdout.trim()
  if ((await git($, ['merge-base', '--is-ancestor', tip, 'HEAD'], r.worktree)).exitCode === 0) {
    await patch($, rid, cur => ({ ...cur, synced: tip }))
    return true
  }
  const m = await patch($, rid, cur => moveTo(cur, 'merging', `syncing with the latest ${remote} and running the checks again`))
  if (m?.phase !== 'merging') return false
  const merged = await git($, ['merge', '--no-edit', remote], r.worktree)
  if (merged.exitCode !== 0) {
    await git($, ['merge', '--abort'], r.worktree)
    await record($, rid, 'merge with the base', `git merge ${remote} failed:\n${tailOf(`${merged.stdout}\n${merged.stderr}`, 20)}`)
    await block($, rid, { on: 'merge' }, `The branch conflicts with the latest ${remote}: resolve it in ${r.worktree} (or /factory rework to have the builder do it), then Retry.`)
    return false
  }
  const found = await checkCommands($, r)
  const results: Check[] = []
  for (const [k, argv] of found.checks.entries()) {
    if (!(await stillIn($, rid, 'merging'))) return false
    await nowRunning($, rid, argv, k, found.checks.length)
    const out = await run$($, argv, r.worktree)
    results.push({ cmd: argv.join(' '), ok: out.exitCode === 0, tail: out.exitCode === 0 ? '' : tailOf(`${out.stdout}\n${out.stderr}`), ...(out.notStarted ? { isMissing: true } : {}), ...(out.timedOut ? { isTimedOut: true } : {}) })
  }
  await record($, rid, `checks on the latest ${remote}`, results.map(c => `${c.isMissing ? '– (not installed)' : c.isTimedOut ? '⏱' : c.ok ? '✓' : '✗'} ${c.cmd}${c.tail ? `\n${c.tail}` : ''}`).join('\n') || 'No checks to run.')
  const bad = results.filter(c => !c.ok && !c.isMissing)
  const after = await patch($, rid, cur => ({ ...cur, checking: null, ...(bad.length ? {} : { synced: tip }) }))
  if (after?.phase !== 'merging') return false
  if (bad.length) {
    await block($, rid, { on: 'merge' }, `Synced with the latest ${remote}, the checks fail: ${bad.map(c => c.cmd).join(', ')}. /factory rework sends it to the builder; Retry runs them again.`, cur => ({ ...cur, checks: results }))
    return false
  }
  return true
}

const prBaseOf = (r: Run) => r.baseRef?.replace(/^(origin|upstream)\//, '') ?? ''

async function openPr($: EngineInterface, rid: string, reason: string, byApprover: boolean) {
  let moved = false
  const r = await patch($, rid, cur => {
    // Queued behind the approval: a run stopped meanwhile stays stopped, and no PR is asked for.
    if (!isLive(cur.phase)) return cur
    moved = true
    const handed = forbidsPush(cur.feature)
    const note = `${reason || 'approved'}. ${handed ? 'The PR commands are handed to you: the feature says not to push' : 'PR requested from Claude'}`
    return { ...moveTo(cur, 'done', note), pr: { state: handed ? 'handed' : 'requested' }, autoMerge: autoMerge && byApprover && !handed, steps: { ...cur.steps, approver: { ...cur.steps.approver, state: 'pass' } } }
  })
  if (!r || !moved) return
  await recordStats($, rid)
  void $.prompt.submit({ text: prPrompt(r, reason, prRepoOf(r, r.remotes?.origin ?? null, r.remotes?.upstream ?? null)) }).catch(() => {
    $.ui.toast(`Approved. Open a PR from ${r.branch} yourself; the prompt could not be sent.`)
  })
  if (r.issue) {
    await setQueue($, rootOf(r), r.issue, 'pr', reason)
    // The next issue starts once Claude reports the PR open (pr-opened), so its link lands on this
    // run; with the commands handed to the person, at once.
    if (r.pr?.state === 'handed') await nextIssue($)
  }
}

// ---------- GitHub issues as the queue ----------

// Draining: /factory run goes on to the next issue each time one parks, is rejected or gets its PR.
let draining = false

async function gh($: EngineInterface, args: string[], cwd: string) {
  return $.process.run(['gh', ...args], { cwd, timeoutMs: 60_000 }).catch(err => ({ exitCode: 1, stdout: '', stderr: String(err) }))
}
const isoNow = async ($: EngineInterface) => new Date(await $.clock.now()).toISOString()
const queuePath = (root: string) => `${root}/.factory/queue.json`
async function queueOf($: EngineInterface, root: string): Promise<Queue> {
  return parseQueue(await $.fs.read(queuePath(root)).then(t => String(t), () => null))
}
async function setQueue($: EngineInterface, root: string, issue: number, state: QueueState, note = '', pr = '') {
  const q = await queueOf($, root)
  const was = q[String(issue)]
  q[String(issue)] = { state, at: await isoNow($), ...(note ? { note: note.slice(0, 300) } : {}), ...(pr || was?.pr ? { pr: pr || was!.pr } : {}) }
  await $.fs.write(queuePath(root), `${JSON.stringify(q, null, 2)}\n`).catch(() => {})
}
// GitHub's REST API, never GraphQL (which Claude Code cloud sessions refuse). The repository is origin's, read
// from its URL: gh's own {owner}/{repo} may pick an upstream remote in a fork checkout, and then the queue would
// read upstream's issues. A remote that isn't GitHub's leaves it to gh. Text goes with -f (raw), so a body
// starting with @ is never read as a file.
const ghSlug = (url: string) => {
  const m = url.trim().match(/github\.com[:/]+([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/i)
  return m ? `${m[1]}/${m[2]}` : null
}
async function remoteSlug($: EngineInterface, root: string, remote: string): Promise<string | null> {
  const out = await git($, ['remote', 'get-url', remote], root).catch(() => null)
  return out && out.exitCode === 0 ? ghSlug(out.stdout) : null
}
async function apiOf($: EngineInterface, root: string) {
  const slug = (await remoteSlug($, root, 'origin')) ?? '{owner}/{repo}'
  return (path: string) => `repos/${slug}/${path}`
}
const issuesQuery = (api: (p: string) => string) => api(`issues?labels=${encodeURIComponent(LABEL)}&state=open&per_page=100`)
// What the factory says on an issue. A failure (no gh, no access) doesn't stop the run: it is toasted.
async function ghComment($: EngineInterface, root: string, issue: number, body: string) {
  const out = await gh($, ['api', '-X', 'POST', (await apiOf($, root))(`issues/${issue}/comments`), '-f', `body=${body}`], root)
  if (out.exitCode !== 0) $.ui.toast(`Factory: couldn't comment on #${issue}: ${tailOf(out.stderr, 1)}`)
}
// Results ignored: a label that already exists (422) or isn't on the issue (404) is fine.
async function ghLabel($: EngineInterface, root: string, issue: number, label: string, add: boolean) {
  if (add) {
    await gh($, ['api', '-X', 'POST', (await apiOf($, root))('labels'), '-f', `name=${label}`, '-f', `color=${label === NEEDS_INFO_LABEL ? 'FBCA04' : 'D93F0B'}`], root)
    await gh($, ['api', '-X', 'POST', (await apiOf($, root))(`issues/${issue}/labels`), '-f', `labels[]=${label}`], root)
  } else {
    await gh($, ['api', '-X', 'DELETE', (await apiOf($, root))(`issues/${issue}/labels/${encodeURIComponent(label)}`)], root)
  }
}
// The operator: whoever gh is logged in as. Their comments on an issue count beside its author's.
async function operatorOf($: EngineInterface, root: string) {
  const out = await gh($, ['api', 'user', '--jq', '.login'], root)
  return out.exitCode === 0 ? out.stdout.trim() : ''
}
async function fetchIssue($: EngineInterface, root: string, n: number): Promise<Issue | string> {
  const failed = (stderr: string) => `Couldn't read issue #${n} with gh: ${tailOf(stderr, 2) || 'gh failed'}`
  const out = await gh($, ['api', (await apiOf($, root))(`issues/${n}`)], root)
  if (out.exitCode !== 0) return failed(out.stderr)
  // Fail closed: no issue from partial comments (a missed answer, a wrong resume).
  const comments = await gh($, ['api', '--paginate', (await apiOf($, root))(`issues/${n}/comments?per_page=100`)], root)
  if (comments.exitCode !== 0) return failed(comments.stderr)
  const issue = parseRestIssue(out.stdout, comments.stdout)
  if (issue === 'pull-request') return `#${n} is a pull request, not an issue: the factory builds open issues only.`
  return issue ?? `gh answered for #${n} in a shape the factory can't read.`
}

// A run on one issue: the issue written to .factory/issues/<n>.md as quoted data, the run's feature
// pointing at it. A parked issue its author answered resumes with their answers for the intake.
async function startIssue($: EngineInterface, n: number, anyway = false): Promise<string> {
  const ready = await preflight($)
  if ('error' in ready) return ready.error
  const { root } = ready
  const going = Object.values(await read($, runs)).find(x => x.issue === n && isLive(x.phase))
  if (going) return `Issue #${n} already has a run: ${going.note} (@${going.slug}).`
  const issue = await fetchIssue($, root, n)
  if (typeof issue === 'string') return issue
  const no = refusal(issue)
  if (no) return no
  const operator = await operatorOf($, root)
  const was = (await queueOf($, root))[String(n)]
  const answers = was?.state === 'needs-info' ? answeredSince(issue, operator, was.at).map(c => c.body.trim()).filter(Boolean) : []
  const file = `${root}/.factory/issues/${n}.md`
  if (!(await $.fs.write(file, issueFile(issue, operator)).then(() => true, () => false))) return `Couldn't write ${file}.`
  if (was?.state === 'needs-info' || was?.state === 'needs-human') {
    await ghLabel($, root, n, was.state === 'needs-info' ? NEEDS_INFO_LABEL : NEEDS_HUMAN_LABEL, false)
  }
  const said = await start($, issueFeature(issue, file), [], { issue: n, issueAnyway: anyway, intakeAnswers: answers })
  if (Object.values(await read($, runs)).some(x => x.issue === n && isLive(x.phase))) await setQueue($, root, n, 'running')
  return said
}

async function queueNow($: EngineInterface): Promise<string> {
  const top = await git($, ['rev-parse', '--show-toplevel'], await $.session.root())
  if (top.exitCode !== 0) return 'Not a git repository.'
  const root = top.stdout.trim()
  const listed = await gh($, ['api', '--paginate', issuesQuery(await apiOf($, root))], root)
  if (listed.exitCode !== 0) return `Couldn't list the issues with gh: ${tailOf(listed.stderr, 2) || 'gh failed'}`
  return queueText(queueLines(parseRestIssueList(listed.stdout), await queueOf($, root), new Set()))
}

// /factory run: the open issues labeled `factory`, oldest first; the first to start or resume starts,
// and the factory goes on to the next each time one is done with it. One run at a time.
async function runQueue($: EngineInterface, quiet = false): Promise<string> {
  const ready = await preflight($)
  if ('error' in ready) return quiet ? '' : ready.error
  const { root } = ready
  const listed = await gh($, ['api', '--paginate', issuesQuery(await apiOf($, root))], root)
  if (listed.exitCode !== 0) return `Couldn't list the issues with gh: ${tailOf(listed.stderr, 2) || 'gh failed'}`
  const open = parseRestIssueList(listed.stdout)
  const queue = await queueOf($, root)
  const operator = open.some(i => queue[String(i.number)]?.state === 'needs-info') ? await operatorOf($, root) : ''
  const answered = new Set<number>()
  for (const i of open) {
    const e = queue[String(i.number)]
    if (e?.state !== 'needs-info') continue
    const full = await fetchIssue($, root, i.number)
    if (typeof full !== 'string' && answeredSince(full, operator, e.at).length) answered.add(i.number)
  }
  // An issue with a run going (this session's) isn't started twice, whatever the queue file says.
  const going = new Set(Object.values(await read($, runs)).filter(x => isLive(x.phase) && x.issue).map(x => x.issue!))
  // Marked running with no run going here: its session ended before it was done, so it starts again.
  const lines = queueLines(open, queue, answered).map(l =>
    going.has(l.number) ? { ...l, action: 'skip' as const, why: 'running now' } : queue[String(l.number)]?.state === 'running' ? { ...l, action: 'resume' as const, why: 'its run ended with an earlier session: starts again' } : l,
  )
  const todo = lines.filter(l => l.action === 'new' || l.action === 'resume')
  draining = todo.length > 0
  if (!todo.length) return quiet ? '' : `Nothing to start.\n${queueText(lines)}`
  // As many as there are free slots; the rest start as runs finish with their issues.
  const free = Math.max(0, concurrency - working(await read($, runs)).length)
  const said: string[] = []
  for (const l of todo.slice(0, free)) said.push(await startIssue($, l.number))
  const waiting = todo.length - Math.min(free, todo.length)
  return [...said, ...(waiting ? [`${waiting} more wait for a free slot (${concurrency} at once).`] : []), queueText(lines)].join('\n')
}

// The run on an issue is done with it (parked, rejected, PR opened): the next one, while draining.
// From a timer, outside the transition that called it: a run starts its agents through the queue.
async function nextIssue($: EngineInterface) {
  if (!draining) return
  $.clock.after(1, () => void runQueue($, true).then(t => t && $.ui.toast(`Factory: ${t.split('\n')[0]}`)))
}

// The run's counters (stats): one change at a time, through patch.
const bump = (r: Run, fn: (s: NonNullable<Run['stats']>) => NonNullable<Run['stats']>): Run =>
  ({ ...r, stats: fn(r.stats ?? { builderStarts: 0, toolCalls: {}, guardRefused: 0, formatMisses: [] }) })

// How the run went, written to its record once it ends or waits on the person for its outcome.
async function recordStats($: EngineInterface, rid: string) {
  const r = await getRun($, rid)
  if (!r?.record) return
  await $.fs.write(`${r.record}/stats.md`, `# stats\n\n${statsReport(r, await $.clock.now()).join('\n')}\n`).catch(() => {})
}

// The run's record: each step's own words in a numbered file, beside the worktree and out of git,
// so what the factory did can be read after the fact. A run from before the record keeps none.
async function record($: EngineInterface, rid: string, label: string, body: string) {
  const r = await patch($, rid, cur => (cur.record ? { ...cur, recorded: (cur.recorded ?? 0) + 1 } : cur))
  if (!r?.record || !body.trim()) return
  const name = `${String(r.recorded ?? 1).padStart(2, '0')}-${slugOf(label)}.md`
  await $.fs.write(`${r.record}/${name}`, `# ${label}\n\n${body.trim()}\n`).catch(() => {})
}

async function onAgentDone($: EngineInterface, rid: string, agentId: string, answer: string, why: string, isApiError: boolean) {
  const r = await getRun($, rid)
  const role = r?.agents[agentId]
  if (!r || !role || !isLive(r.phase)) return
  // An API error on the role's own model (one the account can't use, say): once, the same agent
  // again on the session's model.
  const spawn = spawns.get(agentId)
  if (isApiError && spawn && spawn.hasModel && !spawn.isRetry && !isLimitError(why)) {
    await patch($, rid, cur => ({ ...cur, note: `the ${spawn.review ? `${spawn.review} review` : describe(role, cur)} failed on ${modelOf(cur, role)} (${why}); trying the session's model` }))
    if (await spawnRole($, rid, role, spawn.prompt, { onSessionModel: true, review: spawn.review ?? '' })) return
  }
  const models = `Model asked: ${spawn?.asked ?? 'unknown (spawned before a reload)'}; ran on: ${[...(ranOn.get(agentId) ?? [])].join(', ') || 'no step seen'}.`
  await record($, rid, spawn?.review ? `${spawn.review} review` : describe(role, r), `${models}\n\n${why ? `Stopped: ${why}.${answer.trim() ? `\n\n${answer}` : ''}` : answer}`)
  if (role === 'intake') return r.phase === 'intake' ? onIntake($, rid, answer, why) : undefined
  if (role === 'spec') return r.phase === 'spec' ? onSpec($, rid, answer, why) : undefined
  if (role === 'builder') {
    if (r.phase !== 'build') return
    if (!why && answer.trim()) {
      const tests = parseBuilderTests(answer)
      await patch($, rid, cur => {
        const next = { ...cur, summary: summaryOf(answer), builderTests: tests }
        return tests ? next : bump(next, s => ({ ...s, formatMisses: [...s.formatMisses, `builder (round ${cur.round + 1}): no TESTS line`].slice(-12) }))
      })
    }
    if (why) return block($, rid, { on: 'builder', why }, `The builder stopped: ${why}.${isLimitError(why) ? ' Retry once the limit is lifted: the same builder carries on.' : ''}`, cur => ({ ...cur, steps: { ...cur.steps, builder: { ...cur.steps.builder, state: 'fail' } } }))
    return onBuilt($, rid)
  }
  if (role === 'approver') return r.phase === 'approve' ? onApprover($, rid, answer, why) : undefined
  if (role === 'skeptic') return r.phase === 'review' ? onSkeptic($, rid, answer, why) : undefined
  return onReview($, rid, r.reviews.find(x => x.agentId === agentId)?.role ?? role, agentId, answer, why)
}

async function addTokens($: EngineInterface, rid: string, agentId: string, n: number) {
  await patch($, rid, r => {
    const role = r.agents[agentId]
    if (!role || !n) return r
    if (role === 'security' || role === 'code' || role === 'extra') return { ...r, reviews: r.reviews.map(x => (x.agentId === agentId ? { ...x, tokens: x.tokens + n } : x)) }
    if (role === 'skeptic') return { ...r, skepticTokens: (r.skepticTokens ?? 0) + n }
    if (role === 'intake') return { ...r, intakeTokens: (r.intakeTokens ?? 0) + n }
    const key = role === 'spec' ? 'spec' : role === 'builder' ? 'builder' : 'approver'
    return { ...r, steps: { ...r.steps, [key]: { ...r.steps[key], tokens: r.steps[key].tokens + n } } }
  })
}

// Approve: the plan, the PR the approver approved, or a change the approver escalated. Anything else
// that stopped the run isn't approved past: it's retried or the run is stopped.
// A plan whose gate is goal-run is approved there (its dialog or Goal pane, which passes the goal's task
// ids on with /factory plan-approved): approved here, goal-run's goal would stay proposed and refuse
// every task the builder marks. Only when goal-run is gone meanwhile does the factory approve it itself.
const PLAN_IN_GOAL_RUN = "The plan waits for your approval in goal-run: its dialog, or Approve in the Goal pane (/session-goal opens it). If goal-run already shows it approved, /factory plan-approved starts the build."

async function approveNow($: EngineInterface, rid: string, goalTasks?: GoalTask[], fromGoalRun = false): Promise<string> {
  const r = await getRun($, rid)
  if (!r) return 'No factory run.'
  if (r.phase === 'plan' && r.gate === 'goal-run' && !fromGoalRun && (await goalRunThere($))) return PLAN_IN_GOAL_RUN
  // Queued, not awaited: a prompt submitted while the command's hook still runs is refused.
  if (r.phase === 'plan') {
    void serial($, rid, () => onPlan($, rid, goalTasks ? { approved: true, goalTasks } : { approved: true }))
    return 'Plan approved: the builder starts.'
  }
  // Past the intake's NEEDS-INFO or REJECT: the person's call, recorded as theirs.
  if (r.phase === 'needs-human' && r.blocked?.on === 'intake') {
    void serial($, rid, async () => {
      await record($, rid, 'intake overridden', `The person had it built over the intake's ${r.intake?.verdict ?? 'verdict'}.`)
      await respec($, rid)
    })
    return 'Past the intake: the spec-writer starts.'
  }
  if (r.phase === 'ready' || (r.phase === 'needs-human' && r.blocked?.on === 'escalate')) {
    void serial($, rid, () => finish($, rid, r.phase === 'ready' ? r.note.replace(/\. Open the PR when you're ready$/, '') : 'approved by the person over the approver', r.phase === 'ready'))
    return forbidsPush(r.feature) ? 'Approved: the feature says not to push, so Claude gives you the commands to open the PR.' : 'Approved: Claude opens the PR.'
  }
  if (r.phase === 'needs-human') return `Nothing to approve: ${r.note} /factory retry runs that step again; /factory stop ends the run.`
  return `Nothing waits for approval: the run is ${r.note}.`
}

// Retry: the step that stopped the run, again.
async function retryNow($: EngineInterface, rid: string): Promise<string> {
  const r = await getRun($, rid)
  if (!r || r.phase !== 'needs-human' || !r.blocked) return 'Nothing to retry.'
  if (r.blocked.on === 'escalate') return 'The approver escalated: /factory approve opens the PR anyway, /factory stop ends the run.'
  const b = r.blocked
  void serial($, rid, async () => {
    if (b.on === 'intake' || (b.on === 'start' && b.role === 'intake')) return startIntake($, rid)
    if (b.on === 'merge') return finish($, rid, 'approved', r.steps.approver.state === 'pass')
    if (b.on === 'spec') return respec($, rid)
    if (b.on === 'base') {
      await patch($, rid, cur => moveTo(cur, 'build', 'checking what the branch is built on'))
      return onBuilt($, rid)
    }
    if (b.on === 'builder') return startBuild($, rid, openFindings(r.reviews.filter(x => x.round === r.round)), r.checks.filter(c => !c.ok && !c.isMissing), '', b.why ?? '')
    if (b.on === 'checks' || b.on === 'setup') {
      await patch($, rid, cur => ({ ...cur, checkRound: 0 }))
      return runChecks($, rid)
    }
    if (b.role === 'spec') return respec($, rid)
    if (b.role === 'builder') return startBuild($, rid, openFindings(r.reviews.filter(x => x.round === r.round)), r.checks.filter(c => !c.ok && !c.isMissing))
    if (b.role === 'approver') return startApprover($, rid)
    const now = await patch($, rid, cur => ({
      ...moveTo(cur, 'review', `reviewing, round ${cur.round}`),
      reviews: cur.reviews.map(x => (x.round === cur.round && x.state === 'fail' ? { ...x, state: 'run', agentId: null, findings: [], understood: undefined, notChecked: undefined } : x)),
    }))
    if (now) await spawnReviewers($, rid, now)
  })
  if (b.on === 'intake') return 'Retrying: the intake weighs the feature again.'
  if (b.on === 'merge') return 'Retrying: syncing with the latest base and running the checks again.'
  return `Retrying: ${b.on === 'start' ? `starting the ${describe(b.role, r)}` : b.on === 'setup' ? 'the setup and the checks' : b.on === 'checks' ? 'the checks' : b.on === 'base' ? 'asking which branch the work is on top of' : `the ${b.on === 'spec' ? 'spec-writer' : 'builder'}`}.`
}

// The person sends the change back to the builder with their own words: once the run waits for
// them (the PR ready, an escalation, a step that stopped after the build).
async function reworkNow($: EngineInterface, rid: string, said: string): Promise<string> {
  const r = await getRun($, rid)
  if (!r || !isLive(r.phase)) return 'No factory run to rework.'
  if (!said) return 'Say what to change: /factory rework <what to change>'
  if (r.phase !== 'ready' && r.phase !== 'needs-human') return `Not now: the run is ${r.note}. /factory rework sends it back once it waits for you.`
  // The intake asked: the answers go to its next pass, not to a builder.
  if (r.blocked?.on === 'intake') {
    void serial($, rid, async () => {
      await patch($, rid, cur => ({ ...cur, intakeAnswers: [...(cur.intakeAnswers ?? []), said].slice(-5) }))
      await startIntake($, rid)
    })
    return `The intake weighs it again with your answers: ${said}`
  }
  if (r.steps.builder.state === 'wait') return 'Nothing is built yet: /factory retry runs the step that stopped.'
  void serial($, rid, () => startBuild($, rid, [], [], said))
  return `Sent back to the builder: ${said}`
}

// /factory checks-ok: the person lets the commands the unanswered question named run, without the
// question (a dismissed dialog, or a session with no one to answer it). Only those commands, as they
// were then: when the files that define them changed since, the question comes again.
async function checksOkNow($: EngineInterface, rid: string): Promise<string> {
  const r = await getRun($, rid)
  if (!r || r.phase !== 'needs-human' || r.blocked?.on !== 'checks' || !r.askedChecks) return 'No checks wait for your OK.'
  const key = r.askedChecks
  void serial($, rid, async () => {
    await patch($, rid, cur => ({ ...cur, autoApproved: key, askedChecks: undefined, checkRound: 0 }))
    return runChecks($, rid)
  })
  return `Running them: ${key.replace(/ @ \S*$/, '')}. Not asked again in this run until the files that define them change.`
}

// /factory base <branch>: the branch the work is on top of, when the run asked (or to correct it).
async function baseNow($: EngineInterface, rid: string, ref: string): Promise<string> {
  const r = await getRun($, rid)
  if (!r || !isLive(r.phase)) return 'No factory run.'
  if (!ref) return `The run is based on ${r.baseRef || r.base.slice(0, 12)}. /factory base <branch> moves it.`
  const why = await setBase($, rid, ref)
  if (why) return why
  if (r.phase === 'needs-human' && r.blocked?.on === 'base') {
    void serial($, rid, async () => {
      await patch($, rid, cur => moveTo(cur, 'build', 'checking what the branch is built on'))
      await onBuilt($, rid)
    })
  }
  return `The run is now based on ${ref}: the reviewers, the approver and the PR compare with it.`
}

// Lets the run go on without the check (or install) running now.
async function skipNow($: EngineInterface, rid: string): Promise<string> {
  const r = await getRun($, rid)
  const skipRunning = r ? skippers.get(r.slug) : undefined
  if (!r || r.phase !== 'checks' || !r.checking || !skipRunning) return 'No check is running to skip.'
  const cmd = r.checking.cmd
  skipRunning()
  return `Skipped ${cmd}: the run goes on without it, and the reviewers and the approver are told it didn't run. The process ends at its time limit.`
}

// The agents the run is waiting on now: the step's own, or this round's reviewers still at work.
function waitingOn(r: Run): string[] {
  const ids = Object.entries(r.agents)
  const latest = (role: Role) => ids.filter(([, x]) => x === role).map(([id]) => id).slice(-1)
  if (r.phase === 'intake') return latest('intake')
  if (r.phase === 'spec') return latest('spec')
  if (r.phase === 'build') return r.builderId ? [r.builderId] : latest('builder')
  if (r.phase === 'approve') return latest('approver')
  if (r.phase === 'review') {
    const reviewing = r.reviews.filter(x => x.round === r.round && x.state === 'run' && x.agentId).map(x => x.agentId!)
    return reviewing.length ? reviewing : latest('skeptic')
  }
  return []
}

// Gives up on the agents the step waits on: their tool calls are refused from now on, the step stops
// for the person, and Retry starts new ones (a builder starts fresh from what is in the worktree).
async function abandonNow($: EngineInterface, rid: string, why: string): Promise<string> {
  const r = await getRun($, rid)
  if (!r || !isLive(r.phase)) return 'No factory run.'
  const ids = waitingOn(r)
  if (!ids.length) return `No agent to abandon: the run is ${r.note}.`
  const role = r.agents[ids[0]!]!
  await update($, stoppedAgents, list => [...list.filter(id => !ids.includes(id)), ...ids].slice(-MAX_STOPPED))
  // A skeptic is optional: given up on, it refutes nothing and the findings go to the builder.
  if (role === 'skeptic') {
    void serial($, rid, () => onSkeptic($, rid, '', 'abandoned'))
    return 'Abandoned the skeptic: the findings go to the builder as they are.'
  }
  const said = `Abandoned the ${role === 'extra' || role === 'security' || role === 'code' ? 'stuck reviewers' : describe(role, r)}${why ? ` (${why})` : ''}.`
  await block($, rid, { on: 'start', role: role === 'extra' ? 'code' : role }, `${said} Retry starts a new one.`, cur => ({
    ...cur,
    ...(role === 'builder' ? { builderId: undefined } : {}),
    reviews: cur.reviews.map(x => (ids.includes(x.agentId ?? '') ? { ...x, state: 'fail', agentId: null } : x)),
    steps: role === 'spec' || role === 'builder' || role === 'approver' ? { ...cur.steps, [role]: { ...cur.steps[role], state: 'fail' } } : cur.steps,
  }))
  await record($, rid, 'abandoned', said)
  return `${said} /factory retry (or the Retry button) starts a new one.`
}

// More reviewers for a run under way: from its next review round on (the current one, if not begun).
async function addReviewers($: EngineInterface, rid: string, raw: unknown): Promise<string> {
  const r = await getRun($, rid)
  if (!r || !isLive(r.phase)) return 'No factory run.'
  const { extras, ignored } = extrasFrom([...(r.extras ?? []), ...(Array.isArray(raw) ? raw : [raw])])
  const fresh = extras.filter(e => !r.extras?.some(x => x.name === e.name))
  if (!fresh.length) return `No reviewer added${ignored.length ? `: ${ignored.join(', ')} (unknown with no focus, already there, or past ${MAX_EXTRAS})` : ''}.`
  await patch($, rid, cur => ({ ...cur, extras: [...(cur.extras ?? []), ...fresh], reviews: [...cur.reviews, ...fresh.map(e => reviewOf(e.name))] }))
  return `Added ${fresh.map(e => e.name).join(', ')}: they review from the next round on, beside security and code.`
}

async function statusText($: EngineInterface, rid: string): Promise<string> {
  const r = await getRun($, rid)
  // No run: whether one could start, which is what the person asks when it won't.
  if (!r) return `No factory run in this session.\n${await doctorText($, rid)}\n${nextActionsText(nextActionsOf(null, 0))}`
  const files = r.record ? (await $.fs.list(r.record).catch(() => [])).map(f => f.name).sort() : []
  const repo = await repoOutcomes($, r.kind === 'review' ? r.worktree : rootOf(r))
  return [...runsLines(await read($, runs), r), statusReport(r, await $.clock.now(), files), ...(repo ? [repo] : [])].join('\n')
}

// With several runs: each in a line, and which one the rest of the status is about.
function runsLines(all: Record<string, Run>, shown: Run): string[] {
  const list = Object.values(all).filter(x => isLive(x.phase) || x.slug === shown.slug)
  if (list.length < 2) return []
  return [
    `Runs (${working(all).length} working of ${concurrency} at once; name one with @<run> or the control tool's run):`,
    ...list.map(x => `- ${x.slug}${x.issue ? ` (#${x.issue})` : ''}: ${x.phase}${waitsOnYou(x) ? ', waits on the person' : ''} · ${x.note}${x.slug === shown.slug ? '  ← below' : ''}`),
    '',
  ]
}

// /factory doctor: what a run needs, checked without starting one or spending a token. Each line says
// what is wrong and what to do; read-only (git and the project's files).
async function doctorText($: EngineInterface, rid: string): Promise<string> {
  const items: DoctorItem[] = []
  const cur = await getRun($, rid)
  const busy = working(await read($, runs))
  if (busy.length >= concurrency) items.push({ level: 'block', text: `${busy.length} runs are working, the most the concurrency option allows (${concurrency}): ${busy.map(x => titleOf(x.feature, 40)).join('; ')}. /factory stop @<run> ends one.` })
  else if (cur && isLive(cur.phase)) items.push({ level: 'ok', text: `${busy.length} of ${concurrency} run slots in use: another run can start.` })
  const top = await git($, ['rev-parse', '--show-toplevel'], await $.session.root())
  if (top.exitCode !== 0) {
    items.push({ level: 'block', text: 'Not a git repository: the factory builds on a branch, in a worktree. git init, and commit.' })
    return doctorReport(items)
  }
  const root = top.stdout.trim()
  const head = await git($, ['rev-parse', 'HEAD'], root)
  if (head.exitCode !== 0) {
    items.push({ level: 'block', text: 'No commit yet to build from: commit first.' })
    return doctorReport(items)
  }
  const branch = (await git($, ['rev-parse', '--abbrev-ref', 'HEAD'], root)).stdout.trim()
  items.push({ level: 'ok', text: `Git repository ${root}, ${branch && branch !== 'HEAD' ? `on ${branch}` : 'detached HEAD'} at ${head.stdout.trim().slice(0, 12)}; runs build in ${root}/.factory/<name>.` })
  const dirty = await git($, ['status', '--porcelain'], root)
  const changed = dirty.exitCode === 0 ? dirty.stdout.split('\n').filter(l => l.trim() && !/^\?\? \.factory\//.test(l)).length : 0
  if (changed) items.push({ level: 'warn', text: `${changed} uncommitted change${changed === 1 ? '' : 's'} in your checkout: a run builds from the last commit, without them. Commit first if the feature needs them.` })
  // Commits not on the upstream would go into the run's PR under its description (L4).
  const ahead = await git($, ['rev-list', '--count', '@{upstream}..HEAD'], root)
  const n = ahead.exitCode === 0 ? Number(ahead.stdout.trim()) : 0
  if (n > 0) items.push({ level: 'warn', text: `${branch} is ${n} commit${n === 1 ? '' : 's'} ahead of its upstream: they would be in the run's PR too. Push them first, or start from a branch that has none.` })
  if (await goalRunThere($)) items.push({ level: 'ok', text: 'goal-run is installed: you approve the plan there.' })
  else items.push({ level: 'warn', text: "goal-run isn't installed: the factory asks for the plan's approval in its own band." })
  // The checks, as detection finds them in the checkout (a run's worktree holds the same files).
  try {
    const io: ChecksIO = {
      list: async dir => (await $.fs.list(dir).catch(() => [])).map(f => ({ name: f.name, isDir: String((f as { kind?: string }).kind) === 'dir' || String((f as { kind?: string }).kind) === 'directory' })),
      read: path => $.fs.read(path).then(t => String(t), () => null),
    }
    const checksFile = await $.fs.read(`${root}/.factory/checks.json`).then(t => String(t), () => null)
    const found = await detectProjectChecks(io, root, { explicit: checksOption, touched: [], spec: null, checksFile })
    if (found.checks.length) items.push({ level: 'ok', text: `Checks${checksOption.trim() ? ' (the checks option)' : checksFile ? ' (.factory/checks.json)' : ' found'}: ${found.checks.map(c => c.join(' ')).join('; ')}.` })
    else items.push({ level: 'warn', text: `No checks: ${found.reason || 'none found'} A run's approval then goes to you, since nothing ran. Set the checks option or .factory/checks.json.` })
    for (const w of found.warnings.slice(0, 5)) items.push({ level: 'warn', text: `Checks: ${w}` })
  } catch (e) {
    items.push({ level: 'warn', text: `Couldn't look for checks: ${String(e).slice(0, 120)}` })
  }
  const gh = await $.process.run(['gh', '--version'], { cwd: root, timeoutMs: 10_000 }).catch(() => null)
  items.push(gh && gh.exitCode === 0
    ? { level: 'ok', text: 'gh is installed: Claude can open the PR with it.' }
    : { level: 'warn', text: "gh isn't installed here: Claude opens the PR through another GitHub access it has, or gives you the commands." })
  return doctorReport(items)
}

async function stopNow($: EngineInterface, rid: string): Promise<string> {
  const r = await patch($, rid, cur => (isLive(cur.phase) ? moveTo(cur, 'stopped', 'stopped by the person') : cur))
  if (r) await recordStats($, rid)
  // A stop is for the queue too: no next issue starts by itself.
  draining = false
  if (r?.issue) await setQueue($, rootOf(r), r.issue, 'stopped')
  if (r) await update($, stoppedAgents, ids => [...ids.filter(id => !r.agents[id]), ...Object.keys(r.agents)].slice(-MAX_STOPPED))
  return r ? `Stopped. The branch ${r.branch} and its worktree ${r.worktree} stay; remove them with git worktree remove when done.` : 'No factory run.'
}

// What the person can do when the run waits on them: open the approved PR, approve past an
// escalation, or retry the step that stopped the run.
function actions($: EngineInterface, rid: string, r: Run): { key: string; label: string; press: () => unknown }[] {
  if (r.phase === 'ready') return [{ key: 'pr', label: 'Open PR', press: () => approveNow($, rid) }]
  if (r.phase !== 'needs-human') return []
  if (r.blocked?.on === 'escalate') return [{ key: 'pr', label: 'Approve PR', press: () => approveNow($, rid) }]
  if (r.blocked?.on === 'intake') return [{ key: 'pr', label: 'Build anyway', press: () => approveNow($, rid) }, { key: 'retry', label: 'Ask intake again', press: () => retryNow($, rid) }]
  return [{ key: 'retry', label: 'Retry', press: () => retryNow($, rid) }]
}

// The diagram's frame timer runs only while a run is live: started with one, stopped once it ends.
async function tick($: EngineInterface) {
  const live = Object.values(await read($, runs)).filter(x => isLive(x.phase))
  if (!live.length) return void timers.splice(0).forEach(t => t.cancel())
  // While a check runs nothing in the diagram moves: only the seconds do, and only when they change.
  if (live.some(r => !waitsOnPerson(r.phase) && r.phase !== 'checks')) await update($, frame, f => f + 1)
  // The seconds the band counts: a running check's, or since the agent's last action.
  if (live.some(r => (r.phase === 'checks' && r.checking) || ['intake', 'spec', 'build', 'review', 'approve', 'merging'].includes(r.phase))) {
    const t = await $.clock.now()
    if (Math.floor(t / 1000) !== Math.floor((await read($, now)) / 1000)) await update($, now, () => t)
  }
}

async function ensureTicking($: EngineInterface) {
  const live = Object.values(await read($, runs)).some(x => isLive(x.phase))
  if (live && !timers.length) timers.push($.clock.every(FRAME_MS, () => tick($)))
}

export const register: Register = (on, options) => {
  maxRounds = Math.max(1, Math.min(3, Number(options.maxRounds ?? 2) || 2))
  // Claude Code lets a command run 10 minutes at most: the option can only shorten it.
  skepticOn = String(options.skeptic ?? 'on') !== 'off'
  checkTimeoutMs = Math.max(1, Math.min(10, Number(options.checkTimeout ?? 10) || 10)) * 60_000
  checksOption = String(options.checks ?? '')
  setupOption = String(options.setup ?? '')
  autoPr = String(options.autoPr ?? 'off') === 'on'
  modelsOption = String(options.models ?? 'auto') === 'fixed' ? 'fixed' : 'auto'
  skillsOption = parseSkills(String(options.skills ?? ''))
  intakeOn = String(options.intake ?? 'on') !== 'off'
  autoMerge = String(options.autoMerge ?? 'off') === 'on'
  concurrency = Math.max(1, Math.min(5, Number(options.concurrency ?? 3) || 3))

  on('session.start', async ($, e, next) => {
    for (const t of timers.splice(0)) t.cancel()
    // A job of an earlier session that never settled (a question nobody answered) doesn't hold this one's.
    queues.clear()
    skippers.clear()
    await $.command.register({ name: 'factory', description: 'Run a feature through the software factory: spec, plan, build, checks, reviews, approval', argumentHint: '<feature> | run [<issue> [anyway]] | queue | review [base=<ref>] [what it is for] | approve | retry | rework <note> | status | doctor | stop' })
    for (const role of Object.keys(ROLES) as Role[]) {
      const spec = ROLES[role]
      await $.agent
        .register({ name: spec.name, description: `The factory's ${spec.label}: started by /factory runs only.`, prompt: ROLE_PROMPTS[role], model: spec.model, ...(spec.tools ? { tools: skillsOf(role).length ? [...spec.tools, 'Skill'] : spec.tools } : {}) })
        .catch(() => {})
    }
    // Last, and allowed to fail: the rest of the start must not depend on it.
    await $.tool
      .register({
      name: 'start',
      description: "Start a factory run: its spec-writer writes a spec, you approve its plan, its builder builds it on a branch of its own, the checks and reviewers check it, and an approver decides on the PR. Call it when the person asks for the factory (\"run it in the factory\", /factory), with the feature in their words plus where its details are; then don't do the work yourself.",
      inputSchema: {
        type: 'object',
        properties: {
          feature: { type: 'string', description: 'What to build, in a sentence or a short paragraph, naming the file, issue or to-do item it comes from' },
          followupId: { type: 'string', description: 'Optional: the id of the to-do item this is, from the followups start message' },
          issue: { type: 'number', description: "Optional: a GitHub issue's number, when the work is an open issue labeled factory. The factory reads the issue itself (as data), comments on it, and its PR closes it; the feature can then be its title" },
          reviewers: {
            type: 'array',
            description: `Optional, and for most features none: extra reviewers beside the ones the factory picks (code always; security, ux and ui-design by the intake's risk and surfaces), at most ${MAX_EXTRAS}, only where this change needs that look. A lens by name: ${Object.keys(LENSES).join(', ')} (a UI change: frontend; new paid resources or scaling: finops; migrations, config or a risky release: deploy; hot paths: performance; a public API: api; personal or bulk data: data). Or your own: { name, focus, agent } with agent an agent type of this session that reviews.`,
            items: {
              anyOf: [
                { type: 'string', enum: Object.keys(LENSES) },
                { type: 'object', properties: { name: { type: 'string' }, focus: { type: 'string' }, agent: { type: 'string' } }, required: ['name'] },
              ],
            },
          },
        },
        required: ['feature'],
      },
      isDeferred: false,
    })
      .catch(() => {})
    await $.tool
      .register({
        name: 'review',
        description: "Have the factory's reviewers (security and code, plus any extra you name) review the change already in this checkout, against where its branch left the default branch (uncommitted work included), with no spec, build or approver: a skeptic checks their blocker and major findings, and what stands comes back to you to fix. Call it when the person asks for a factory review, or once you finished a sizeable change yourself; not for a one-line fix.",
        inputSchema: {
          type: 'object',
          properties: {
            focus: { type: 'string', description: 'What the change is for, in a sentence: the reviewers judge it against this' },
            base: { type: 'string', description: 'Optional: the branch or commit to compare with, when not the default branch' },
            reviewers: { type: 'array', description: `Optional extra reviewers, as for the start tool: ${Object.keys(LENSES).join(', ')}, or { name, focus, agent }`, items: {} },
          },
          required: ['focus'],
        },
        isDeferred: false,
      })
      .catch(() => {})
    await $.tool
      .register({
        name: 'control',
        description: "Steer the factory run for the person. skip-check: go on without the check (or install) running now. abandon-agent: give up on the agent the step waits on (a stuck one: no activity for long), so Retry starts a new one. add-reviewers: extra reviewers from the next round on (reviewers: lens names or { name, focus, agent }), only when the change needs that look. retry: run again the step that stopped the run. stop: end the run. pr-opened: the PR of an approved run is open (url: its link); only after you opened it, or the person did. findings: what became of each finding a review sent back (outcomes: fixed, not-a-bug with why, wont-fix). Use it when the person asks, or when the status tool shows a step stuck, and tell the person what you did and why.",
        inputSchema: {
          type: 'object',
          properties: {
            action: { type: 'string', enum: ['skip-check', 'abandon-agent', 'add-reviewers', 'retry', 'stop', 'pr-opened', 'findings'] },
            outcomes: { type: 'array', description: 'For findings: what became of each finding the review sent back', items: { type: 'object', properties: { id: { type: 'string', description: 'F1, F2...' }, outcome: { type: 'string', enum: ['fixed', 'not-a-bug', 'wont-fix'] }, why: { type: 'string' } }, required: ['id', 'outcome'] } },
            url: { type: 'string', description: "For pr-opened: the link of the PR you opened for the approved run" },
            reason: { type: 'string', description: 'Why, in a few words: the run records it' },
            reviewers: { type: 'array', description: 'For add-reviewers: lens names or { name, focus, agent }', items: {} },
            run: { type: 'string', description: 'Which run, when several are going: its name (the status lists them) or its issue number. Omitted: the one waiting on the person, else the newest' },
          },
          required: ['action'],
        },
        isDeferred: false,
      })
      .catch(() => {})
    await $.tool
      .register({
        name: 'status',
        description: "Where the factory run stands: its step and for how long, the agent's last action, the checks with their output, the reviewers' findings, what it waits on, and the folder with each step's own words. It ends with the next actions: which are yours (through the control tool) and which are the person's to take. With no run, it checks whether one could start (git, checks, goal-run, gh). Call it when the person asks how the factory run is going, why it seems stuck or why it won't start, before guessing.",
        inputSchema: { type: 'object', properties: {} },
        isDeferred: false,
      })
      .catch(() => {})
    await ensureTicking($)
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    for (const t of timers.splice(0)) t.cancel()
    return next(e)
  }).catch(($, e, next) => next(e))

  // The roles are the factory's: the model doesn't dispatch them itself.
  on('agent.offer', async ($, e, next) => (e.agent.startsWith('factory:') ? { isOffered: false } : next(e)))

  // A stopped run's agents can't be aborted, so their every tool call is refused: they stop editing
  // and spending. Only the run's own agents; the main loop and other agents go on.
  on('tool.call', async ($, e, next) => {
    if (e.agentId !== undefined) {
      // A state read that fails can't let a run agent's push through: the agents this module started
      // are known without it (spawns), and the guard below still applies to them.
      const r = await agentRun($, e.agentId).catch(() => null)
      const rid = r?.slug ?? ''
      if (!r && spawns.has(e.agentId)) {
        const what = forbiddenOf(e)
        if (what) return { deny: forbiddenDeny(what) }
      }
      if ((r?.agents[e.agentId] && !isLive(r.phase)) || (await read($, stoppedAgents)).includes(e.agentId)) return { deny: STOPPED_DENY }
      // A review's agents look at the person's own checkout: they never change a file in it.
      if (r?.agents[e.agentId] && r.kind === 'review' && ['Edit', 'Write', 'MultiEdit', 'NotebookEdit'].includes(e.tool)) {
        // The count is the stats' only: a write that fails never turns the refusal into a pass.
        await patch($, rid, cur => bump(cur, s => ({ ...s, guardRefused: s.guardRefused + 1 }))).catch(() => null)
        return { deny: "A factory review changes no file: report what you found, and Claude fixes it." }
      }
      // Nor through the shell: git stash, git checkout -- ., sed -i, a redirect into a file.
      const inReview = r?.agents[e.agentId] && r.kind === 'review' && (e.tool === 'Bash' || e.tool === 'PowerShell') ? forbiddenInReview(String((e as unknown as { command?: unknown }).command ?? '')) : ''
      if (inReview) {
        await patch($, rid, cur => bump(cur, s => ({ ...s, guardRefused: s.guardRefused + 1 }))).catch(() => null)
        return { deny: `A factory review changes nothing in your checkout (${inReview}): read and run read-only commands, write scratch files under /tmp, and report what you found.` }
      }
      // Pushing, publishing, deploying or deleting outside the worktree is never a run agent's job.
      // A guard that fails refuses the call, for the run's agents only.
      if (r?.agents[e.agentId]) {
        const what = forbiddenOf(e)
        if (what) {
          await patch($, rid, cur => bump(cur, s => ({ ...s, guardRefused: s.guardRefused + 1 }))).catch(() => null)
          return { deny: forbiddenDeny(what) }
        }
      }
      // What the run's agent does now: the band shows it, so a working step never reads as stuck.
      const role = r?.agents[e.agentId]
      if (role) {
        // Past twice its budget an agent's calls are refused, so it answers with what it has. The hand-back
        // and the answer itself are not tool calls of its work.
        const budget = r.agentBudgets?.[e.agentId] ?? 0
        const used = r.agentCalls?.[e.agentId] ?? 0
        if (budget > 0 && used >= BUDGET_STOP * budget && e.tool !== 'SubagentHandback') {
          const who = `${describe(role, r)} ${used}/${budget}`
          await patch($, rid, cur => bump(cur, s => ({ ...s, guardRefused: s.guardRefused + 1, overBudget: [...new Set([...(s.overBudget ?? []).filter(x => !x.startsWith(`${describe(role, r)} `)), who])] }))).catch(() => null)
          return { deny: budgetDeny(used, budget) }
        }
        const t = await $.clock.now()
        const text = activityText(e.tool, e as unknown as Record<string, unknown>)
        await patch($, rid, cur => bump({ ...cur, agentCalls: { ...cur.agentCalls, [e.agentId!]: (cur.agentCalls?.[e.agentId!] ?? 0) + 1 }, activity: { role, text, at: t, calls: (cur.activity?.role === role ? cur.activity.calls : 0) + 1 } }, s => ({ ...s, toolCalls: { ...s.toolCalls, [role]: (s.toolCalls[role] ?? 0) + 1 } })))
        await update($, now, () => t)
      }
    }
    return next(e)
    // Whatever failed above, a run agent's forbidden call is still refused: the guard fails closed for
    // the agents it guards, and open (the call goes on) for everyone else.
  }).catch(($, e, next) => {
    const what = e.agentId !== undefined && spawns.has(e.agentId) ? forbiddenOf(e) : ''
    return what ? { deny: forbiddenDeny(what) } : next(e)
  })

  on('tool.call', { tool: REVIEW_TOOL }, async ($, e) => {
    if ((e as { agentId?: string }).agentId !== undefined) return { deny: 'Only the main conversation starts a factory review.' }
    const input = e as unknown as { focus?: unknown; base?: unknown; reviewers?: unknown }
    const { extras } = extrasFrom(input.reviewers)
    return { result: await startReview($, String(input.focus ?? ''), String(input.base ?? ''), extras) }
  })

  // The main Claude asks where a run stands: what it waits on, what failed and where to read more.
  on('tool.call', { tool: STATUS_TOOL }, async $ => ({ result: await statusText($, '') }))

  // The main Claude steers a run for the person: frees a stuck step, adds reviewers, retries or stops.
  on('tool.call', { tool: CONTROL_TOOL }, async ($, e) => {
    if ((e as { agentId?: string }).agentId !== undefined) return { deny: "Only the main conversation steers a factory run." }
    const input = e as unknown as { action?: unknown; reason?: unknown; reviewers?: unknown; run?: unknown }
    const why = String(input.reason ?? '').trim().slice(0, 200)
    // The run it steers: named (its slug, or an issue's number), else the one waiting on the person or the newest.
    const named = String(input.run ?? '').trim().replace(/^@/, '')
    const t = await targetOf($, named ? `x @${/^\d+$/.test(named) ? '#' : ''}${named}` : 'x')
    if (t.error) return { result: t.error }
    const rid = t.rid
    switch (String(input.action ?? '')) {
      case 'skip-check': return { result: await skipNow($, rid) }
      case 'abandon-agent': return { result: await abandonNow($, rid, why) }
      case 'add-reviewers': return { result: await addReviewers($, rid, input.reviewers) }
      case 'retry': return { result: await retryNow($, rid) }
      case 'stop': return { result: await stopNow($, rid) }
      case 'pr-opened': return { result: await prOpened($, rid, String((input as { url?: unknown }).url ?? '')) }
      case 'findings': return { result: await reportOutcomes($, rid, (input as { outcomes?: unknown }).outcomes) }
      default: return { deny: 'action is skip-check, abandon-agent, add-reviewers, retry, stop, pr-opened or findings.' }
    }
  })

  // Claude starts a run itself when the person asks for the factory in words, or after /factory.
  on('tool.call', { tool: START_TOOL }, async ($, e) => {
    if ((e as { agentId?: string }).agentId !== undefined) return { deny: 'Only the main conversation starts a factory run.' }
    const input = e as unknown as { feature?: unknown; followupId?: unknown; issue?: unknown }
    // A GitHub issue: its run reads the issue itself, as data; the feature's words aren't needed.
    const issueNo = Number(input.issue)
    if (Number.isInteger(issueNo) && issueNo > 0) return { result: `${await startIssue($, issueNo)} ${STARTED_NOTE}` }
    const feature = String(input.feature ?? '').trim()
    if (!feature) return { deny: 'Name the feature: what to build, and where its details are (a file, an issue, the to-do item).' }
    const id = String(input.followupId ?? '').trim()
    const { extras, ignored } = extrasFrom((input as { reviewers?: unknown }).reviewers)
    const said = await start($, factoryArgs(feature, id || undefined), extras)
    const added = extras.length ? ` Extra reviewers: ${extras.map(x => x.name).join(', ')}.` : ''
    const left = ignored.length ? ` Not added: ${ignored.join(', ')} (unknown with no focus, a duplicate, or past ${MAX_EXTRAS}).` : ''
    return { result: /^Factory run started/.test(said) ? `${said}${added}${left}\n${STARTED_NOTE}` : said }
  })

  on('command.run', { command: 'factory' }, async ($, e) => {
    let arg = e.args.trim()
    // goal-run's answer to the plan, sent on as a command: heard whatever order the mods' hooks run in.
    const told = parsePlanResultArgs(arg)
    if (told !== undefined) {
      const pid = await planRun($)
      if (told) void serial($, pid, () => onPlan($, pid, told))
      return { text: told ? "The factory has goal-run's answer to its plan." : "goal-run's answer to the plan couldn't be read." }
    }
    const approved = parsePlanApprovedArgs(arg)
    if (approved) {
      const pid = await planRun($)
      return { text: await approveNow($, pid, approved.goalTasks, true) }
    }
    // A command for one run names it with a trailing @<run> or @#<issue>; else the one waiting on
    // the person, or the newest.
    let rid = ''
    if (/^(approve|retry|stop|checks-ok|skip|abandon|reviewers|base|rework|status)\b/.test(arg)) {
      const t = await targetOf($, arg)
      if (t.error) return { text: t.error }
      arg = t.rest.trim()
      rid = t.rid
    }
    if (arg === 'approve') return { text: await approveNow($, rid) }
    if (arg === 'retry') return { text: await retryNow($, rid) }
    if (arg === 'stop') return { text: await stopNow($, rid) }
    if (arg === 'status') return { text: await statusText($, rid) }
    if (arg === 'doctor') return { text: await doctorText($, rid) }
    if (arg === 'checks-ok') return { text: await checksOkNow($, rid) }
    if (arg === 'review' || arg.startsWith('review ')) {
      const rest = arg.slice(6).trim()
      const named = /^base=(\S+)\s*/.exec(rest)
      return { text: await startReview($, named ? rest.slice(named[0].length) : rest, named?.[1] ?? '') }
    }
    // The issue queue: /factory run drains it, /factory run <n> runs one (anyway: past the intake's
    // NEEDS-INFO or REJECT, which then stops for you), /factory queue shows it.
    if (arg === 'run') return { text: await runQueue($) }
    const one = /^run\s+#?(\d+)(\s+anyway)?$/.exec(arg)
    if (one) {
      draining = false
      return { text: await startIssue($, Number(one[1]), !!one[2]) }
    }
    if (arg === 'queue') return { text: await queueNow($) }
    if (arg === 'skip') return { text: await skipNow($, rid) }
    if (arg === 'abandon') return { text: await abandonNow($, rid, 'by the person') }
    if (arg.startsWith('reviewers ')) return { text: await addReviewers($, rid, arg.slice(10).split(/[\s,]+/).filter(Boolean)) }
    if (arg === 'base' || arg.startsWith('base ')) return { text: await baseNow($, rid, arg.slice(4).trim()) }
    if (arg === 'rework' || arg.startsWith('rework ')) return { text: await reworkNow($, rid, arg.slice(6).trim()) }
    if (!arg) {
      await $.ui.open({ id: PANE, title: PANE_TITLE })
      const r = await getRun($, rid)
      if (r && isLive(r.phase)) return { text: `${titleOf(r.feature, 120)}: ${r.note}.` }
      // Nothing running: Claude names the work from the conversation and starts it with the tool.
      // From a timer: a prompt submitted while the command's own hook still runs is refused.
      $.clock.after(1, () => void $.prompt.submit({ text: FROM_CONVERSATION }).catch(() => $.ui.toast('/factory <feature> starts a run')))
      return { text: 'Asked Claude to start a run from what this conversation is working on.' }
    }
    // A run going and one word that isn't a subcommand: a mistyped one (plan-approve), not a feature.
    const cur = await getRun($, rid)
    if (cur && isLive(cur.phase) && /^[\w-]+$/.test(arg)) {
      return { text: `"/factory ${arg}" isn't a factory command. While a run goes: /factory approve, plan-approved (the plan goal-run approved), retry, rework <what to change>, checks-ok, status, doctor, stop. /factory review reviews the checkout's change.` }
    }
    return { text: await start($, arg) }
  })

  // Each agent's answer moves the run on, in the queue (see serial).
  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (e.agentId !== undefined) {
      const id = e.agentId
      const why = whyEnded(e)
      const owner = await agentRun($, id).catch(() => null)
      if (owner) {
        const rid = owner.slug
        void serial($, rid, () => onAgentDone($, rid, id, e.answer, why, e.reason === 'error'))
      }
    }
    return r
  }).catch(($, e, next) => next(e))

  on('turn.step', async function* ($, e, next) {
    const r = yield* next(e)
    const u = r.usage
    const owner = e.agentId !== undefined && u ? await agentRun($, e.agentId) : null
    if (owner && e.agentId !== undefined && u) {
      const rid = owner.slug
      await addTokens($, rid, e.agentId, (u.input_tokens ?? 0) + (u.output_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0))
      if (u.model) ranOn.set(e.agentId, (ranOn.get(e.agentId) ?? new Set()).add(u.model))
      const model = String(u.model || 'unknown')
      await patch($, rid, cur => ({ ...cur, usage: { ...cur.usage, [model]: addUsage(cur.usage?.[model], u) } }))
    }
    return r
  }).catch(async function* ($, e, next) { return yield* next(e) })

  // goal-run's plan dialog answers for the spec's tasks: approved, changes for the spec-writer, or
  // kept (the person's own goal stays; the factory asks). Read from the tool call and from
  // PostToolUse, whichever reaches the factory (the mods' order).
  on('tool.call', { tool: PLAN_TOOL }, async ($, e, next) => {
    const r = await next(e)
    const outcome = parsePlanOutcome(String(r.result ?? ''))
    if (outcome) {
      const pid = await planRun($)
      void serial($, pid, () => onPlan($, pid, outcome))
    }
    return r
  }).catch(($, e, next) => next(e))

  on('classic.PostToolUse', async ($, e, next) => {
    const r = await next(e)
    if (e.tool_name === PLAN_TOOL) {
      const outcome = parsePlanOutcome(toolText(e.tool_response))
      if (outcome) {
        const pid = await planRun($)
        void serial($, pid, () => onPlan($, pid, outcome))
      }
    }
    return r
  }).catch(($, e, next) => next(e))

  // ---------- the band ----------

  // One line per live run: the one waiting on the person (or the newest) first, its buttons keyed
  // plainly; the others' keys carry their run's name.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const all = await read($, runs)
    const first = pickRun(all)
    const live = Object.values(all).filter(x => isLive(x.phase)).sort((a, b) => (a.slug === first?.slug ? -1 : b.slug === first?.slug ? 1 : 0))
    if (e.props.hasSurvey || !live.length) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    const t = await read($, now)
    const below = await next(e)
    return (
      <Box flexDirection="column">
        {live.map((r, i) => {
          const rid = r.slug
          const k = (key: string) => (i === 0 ? `f-${key}` : `f-${key}-${r.slug}`)
          return (
            <Box key={`run-${r.slug}`} flexDirection="row" gap={1} paddingX={1} alignItems="center">
              <Text bold color={waitsOnYou(r) ? '#d97706' : ACCENT} wrap="truncate-end">{`🏭 ${runTitle(r, 60)}`}</Text>
              <Text color={waitsOnYou(r) ? '#d97706' : ACCENT}>{`${progressBar(progressOf(r), 10)} ${progressOf(r)}%`}</Text>
              <Text color={isQuiet(r, t) ? '#d97706' : undefined} dimColor={!isQuiet(r, t)} wrap="truncate-end">{`· ${statusOf(r, t)} · ${tok(tokensOf(r))} tokens${costTag(r)}`}</Text>
              {r.phase === 'plan' && r.gate === 'factory' ? <Button key={k('approve-plan')} label="Approve plan" variant="primary" onPress={() => approveNow($, rid)} /> : null}
              {actions($, rid, r).map(a => <Button key={k(a.key)} label={a.label} variant="primary" onPress={a.press} />)}
              {i === 0 ? <Button key="f-open" label="Open" onPress={() => $.ui.open({ id: PANE, title: PANE_TITLE })} /> : null}
              <Button key={k('stop')} label="Stop" onPress={() => stopNow($, rid)} />
            </Box>
          )
        })}
        {below}
      </Box>
    )
  })

  // ---------- the pane ----------

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const Svg = e.surface === 'terminal' ? null : ($.ui.resolve(e as typeof e & { surface: 'desktop' }).Svg ?? null)
    const r = await getRun($, '')
    if (!r) {
      return (
        <Box flexDirection="column" gap={1}>
          <Text bold color={ACCENT}>🏭 Factory</Text>
          <Text dimColor>No run yet. /factory &lt;feature&gt; writes a spec, has you approve its plan, builds it on a branch, runs the checks and the reviews, and asks the approver. You open the PR.</Text>
        </Box>
      )
    }
    const rid = r.slug
    // The other runs, a line each: /factory status @<run> or the band reaches them.
    const others = Object.values(await read($, runs)).filter(x => x.slug !== r.slug && isLive(x.phase))
    const f = await read($, frame)
    const t = await read($, now)
    const findings = r.reviews.filter(x => x.round === r.round && x.findings.length)
    const failed = r.checks.filter(c => !c.ok && !c.isMissing)
    return (
      <Box flexDirection="column" gap={1}>
        {others.length ? (
          <Box flexDirection="column">
            <Text dimColor>{`Also running (${others.length}):`}</Text>
            {others.map(x => <Text key={`o-${x.slug}`} dimColor wrap="truncate-end">{`  ${runTitle(x, 50)} · ${x.note} · @${x.slug}`}</Text>)}
          </Box>
        ) : null}
        <Box flexDirection="column">
          <Text bold color={ACCENT} wrap="truncate-end">{`🏭 ${runTitle(r, 80)}`}</Text>
          {titleOf(r.feature) !== r.feature.trim() ? <Text dimColor wrap="wrap">{r.feature.trim()}</Text> : null}
          <Text color={waitsOnYou(r) ? '#d97706' : ACCENT}>{`${progressBar(progressOf(r), 24)} ${progressOf(r)}%${r.phaseSince ? ` · this step ${mmss(Math.max(0, t - r.phaseSince))}` : ''}`}</Text>
          <Text color={waitsOnYou(r) || isQuiet(r, t) ? '#d97706' : undefined} dimColor={!(waitsOnYou(r) || isQuiet(r, t))} wrap="truncate-end">{`${statusOf(r, t)} · ${tok(tokensOf(r))} tokens${costTag(r)} · spec ${r.specFile}`}</Text>
          <Text dimColor wrap="truncate-end">{`Based on ${r.baseRef || r.base.slice(0, 12)} · ask Claude "how is the factory run going?" for the details`}</Text>
          {r.stat || r.summary ? <Text wrap="wrap">{`Changed: ${[r.stat, r.summary].filter(Boolean).join(' · ')}`}</Text> : null}
          {r.recorded ? <Text dimColor wrap="truncate-end">{`What each step said: ${r.record}/`}</Text> : null}
        </Box>
        {Svg ? (
          <Svg source={diagramSvg(r, f, await read($, theme))} alt={pipelineLines(r).join('; ')} width={DIAGRAM.width} height={DIAGRAM.height} />
        ) : (
          <Box flexDirection="column">{pipelineLines(r).map((l, i) => <Text key={`p-${i}`}>{l}</Text>)}</Box>
        )}
        {findings.length ? (
          <Box flexDirection="column">
            <Text bold>{`Round ${r.round} findings`}</Text>
            {findings.flatMap(x => x.findings.map((g, i) => (
              <Text key={`f-${x.role}-${i}`} wrap="truncate-end">{`${x.role} · [${g.severity}] ${g.where} ${g.text}`}</Text>
            )))}
          </Box>
        ) : null}
        {r.skipped?.length ? (
          <Text dimColor wrap="truncate-end">{`Left out of the commits: ${r.skipped.join(', ')}`}</Text>
        ) : null}
        {failed.length ? (
          <Box flexDirection="column">
            <Text bold color="#dc2626">Failing checks</Text>
            {failed.map((c, i) => <Text key={`c-${i}`} dimColor wrap="truncate-end">{`$ ${c.cmd}: ${c.tail.split('\n').slice(-1)[0] ?? ''}`}</Text>)}
          </Box>
        ) : null}
        <Box flexDirection="row" gap={1}>
          {r.phase === 'plan' && r.gate === 'factory' ? <Button key="p-approve-plan" label="Approve plan" variant="primary" onPress={() => approveNow($, rid)} /> : null}
          {r.phase === 'plan' && r.gate === 'goal-run' ? <Text dimColor>{PLAN_IN_GOAL_RUN}</Text> : null}
          {actions($, rid, r).map(a => <Button key={`p-${a.key}`} label={a.label} variant="primary" onPress={a.press} />)}
          {isLive(r.phase) ? <Button key="p-stop" label="Stop" onPress={() => stopNow($, rid)} /> : null}
        </Box>
      </Box>
    )
  })
}
