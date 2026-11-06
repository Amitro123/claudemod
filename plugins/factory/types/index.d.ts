// A step's state, as the pane draws it.
export type StepState = 'wait' | 'run' | 'pass' | 'changes' | 'fail' | 'skip'
// skeptic: before the builder is sent back, it tries to refute the round's blocker and major findings.
// extra: a reviewer the main Claude added for this run (a lens of the factory's, or an agent of its own).
export type Role = 'spec' | 'builder' | 'security' | 'code' | 'approver' | 'skeptic' | 'extra'
// How big the spec-writer judged the feature: what the models of the later roles follow.
export type Size = 'small' | 'medium' | 'large'
// security and code always review; an extra reviewer is named by the main Claude (frontend, finops...).
export type Reviewer = string
// An extra reviewer: its name, what it looks at, and the agent type that runs it (the factory's own
// generic reviewer when none is named).
export type Extra = { name: string; focus: string; agent?: string }
export type Severity = 'blocker' | 'major' | 'minor'
export type Finding = { severity: Severity; where: string; text: string }
// A task of the spec's breakdown: what goes to goal-run's plan.
export type SpecTask = { title: string; priority: 'high' | 'medium' | 'low'; dependsOn: number[] }
// isMissing: the command couldn't start here (its program isn't installed): skipped, not failed, so the
// builder isn't sent to fix what it can't.
// isTimedOut: it ran past the checks' time limit: the person decides, not the builder.
// isSkipped: the person (or the main Claude for them) let the run go on without waiting for it.
// why: what a check that didn't run said instead (pytest that collected no tests, say).
export type Check = { cmd: string; ok: boolean; tail: string; isMissing?: boolean; isTimedOut?: boolean; isSkipped?: boolean; why?: string }
// agentId: the reviewer's agent this round (null until started), so a late answer from an earlier one is ignored.
// understood: what the reviewer says the change must do, in its own words (a misread spec shows there);
// notChecked: what it says it did not verify. Both from its answer, absent when it gave none.
export type Review = { role: Reviewer; state: StepState; findings: Finding[]; tokens: number; round: number; agentId: string | null; understood?: string; notChecked?: string[] }
// Where the run is: each phase waits on one thing (an agent, the checks, the person).
// 'ready': the approver said APPROVE; the PR waits for the person's Open PR.
export type Phase = 'spec' | 'plan' | 'build' | 'checks' | 'review' | 'approve' | 'ready' | 'needs-human' | 'done' | 'stopped'
// Why a run is at needs-human: what stopped it decides what the person can do (Approve only after an
// ESCALATE; Retry for the rest).
export type Blocked =
  | { on: 'escalate' }
  | { on: 'spec' }
  // why: the builder stopped mid-job (not just failed to commit): Retry sends it on.
  | { on: 'builder'; why?: string }
  | { on: 'checks' }
  | { on: 'setup' }
  | { on: 'start'; role: Role }
  // The builder's branch no longer starts from the run's base: which branch it is on top of is asked.
  | { on: 'base' }

export type Run = {
  feature: string
  slug: string
  phase: Phase
  // Review rounds so far (builder rounds follow them), and builder passes for red checks.
  round: number
  checkRound: number
  startedAt: number
  // The git branch and worktree the run builds in, and the commit it started from.
  base: string
  branch: string
  worktree: string
  specFile: string
  tasks: SpecTask[]
  // The tasks as goal-run numbered them (by priority and dependencies), once it approved the plan:
  // the ids the builder marks.
  goalTasks?: { id: string; title: string }[]
  // The spec-writer's judgment of the feature, and the model each role runs on in this run.
  size?: Size
  models?: Partial<Record<Role, string>>
  // The builder that built this run: each later round goes back to it (it keeps what it read and
  // why), until it fails and a fresh one is started.
  builderId?: string
  // The commands the factory found in the project (no checks or setup option) that the person let
  // run, with the last commit of the files that define them: a change there asks again.
  autoApproved?: string
  // Where the run keeps what each step said (its record), and how many entries it has written.
  record?: string
  recorded?: number
  // What the builder says it changed (its closing summary), and git's count of the change.
  summary?: string
  stat?: string
  // The builder's own test run, from its TESTS: line (its last round's): what reviewers and the
  // approver are told, and a reported failure turns an APPROVE into the person's call.
  builderTests?: { text: string; failing: boolean }
  // The PR, once the run is done: asked of the main Claude (requested), opened (it reported the link
  // with the control tool), or handed to the person as commands when the feature says not to push.
  pr?: { state: 'requested' | 'opened' | 'handed'; url?: string }
  // The commands the factory found that wait for the person's OK, when the question went unanswered
  // (dismissed, or no one there to answer it): /factory checks-ok lets exactly these run.
  askedChecks?: string
  // This round's whole diff, written by the factory beside the record: the reviewers read it instead
  // of running git, which a session with no one to approve it refuses.
  diffFile?: string
  // New files the setup command wrote in the worktree (a lockfile npm install made): never committed.
  setupFiles?: string[]
  // review: only the reviewers (and the skeptic), on the change already in the person's checkout,
  // against `base`; no spec, build, checks or approver. Their findings go back to the main Claude.
  // `worktree` is then that checkout, and `untracked` its new files git doesn't diff.
  kind?: 'review'
  untracked?: string[]
  // The project's test commands as detection found them, for a review run (it runs no checks): the
  // reviewers are told them, so none guesses one.
  testCommands?: string[]
  // How the run went, for its record and the status: builder starts, the run agents' tool calls the
  // mod saw (by role), the calls its guard refused, and answers that missed a marker their prompt asks for.
  stats?: { builderStarts: number; toolCalls: Record<string, number>; guardRefused: number; formatMisses: string[] }
  steps: Record<'spec' | 'builder' | 'checks' | 'approver', { state: StepState; tokens: number }>
  checks: Check[]
  // Why no check ran, or what detection warned about: what the reviewers and the approver are told.
  checksNote?: string
  reviews: Review[]
  // The agents this run spawned, by agentId: the role each one plays.
  agents: Record<string, Role>
  // What the person or the approver said last: the reason a run waits on them.
  note: string
  blocked: Blocked | null
  // Who approves the plan: goal-run's dialog, or the factory's own band (no goal-run, or the person
  // has a goal of their own).
  gate: 'goal-run' | 'factory'
  // The dependencies were installed in the worktree (the setup command ran).
  setupDone: boolean
  // New files the factory left out of its commits: dependencies, build output, credentials.
  skipped?: string[]
  // The followups to-do item the run came from: marked done once the PR is open.
  followupId?: string
  // The command the checks (or the setup before them) are running now, its place among them and when
  // it started: what the band and the pane show, so a long check reads as running, not stuck.
  checking?: { cmd: string; index: number; total: number; since: number; isSetup?: boolean } | null
  // The factory's question before it runs the checks it found is open: the run waits on the person.
  isAskingChecks?: boolean
  // The branch the run started from (the checkout's), and the one the PR goes into; base may move to
  // another branch's commit when the builder built on top of it.
  baseRef?: string
  // When the run entered its current phase, and what its agents did last: the band shows the step's
  // time and the latest action, so a run that is working never reads as stuck.
  phaseSince?: number
  activity?: { role: Role; text: string; at: number; calls: number }
  // Where the progress stood when the run stopped to wait (needs-human) or was stopped.
  lastProgress?: number
  // What this round's diff calls for (its review route), and the skeptic's round: the findings it was
  // asked to refute, with the reviewer each came from, and what its rulings dropped.
  route?: { deep: boolean; focus: string[] }
  disputed?: { role: Reviewer; finding: Finding }[]
  refuted?: { role: Reviewer; finding: Finding; ruling: string; why: string }[]
  skepticTokens?: number
  // Reviewers the main Claude added for this run, beside security and code.
  extras?: Extra[]
}

declare module 'claude-code' {
  interface PluginState {
    factory: {
      run: Run | null
      frame: number
      theme: 'dark' | 'light'
      now: number
      stoppedAgents: string[]
    }
  }
}
