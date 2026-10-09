import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Ctx, Limit, Mood } from '../types'
import { DONE_SECONDS, ERROR_SECONDS, HARD_SECONDS, SCENE_HEIGHT, SCENE_WIDTH, sceneSvg } from './scene'

const mood = atom({ plugin: 'clawd-hud', key: 'mood' } as const, 'idle' as Mood)
const moodAt = atom({ plugin: 'clawd-hud', key: 'moodAt' } as const, 0)
const frame = atom({ plugin: 'clawd-hud', key: 'frame' } as const, 0)
const cacheAt = atom({ plugin: 'clawd-hud', key: 'cacheAt' } as const, null as number | null)
const now = atom({ plugin: 'clawd-hud', key: 'now' } as const, 0)
const minute = atom({ plugin: 'clawd-hud', key: 'minute' } as const, 0)
const ctx = atom({ plugin: 'clawd-hud', key: 'ctx' } as const, null as Ctx | null)
const limits = atom({ plugin: 'clawd-hud', key: 'limits' } as const, [] as Limit[])
const eureka = atom({ plugin: 'clawd-hud', key: 'eureka' } as const, false)
const loopSince = atom({ plugin: 'clawd-hud', key: 'loopSince' } as const, null as number | null)
const toolCounts = atom({ plugin: 'clawd-hud', key: 'toolCounts' } as const, {} as Record<string, number>)
const cost = atom({ plugin: 'clawd-hud', key: 'cost' } as const, null as number | null)

// Personal plans meter a 5-hour and a weekly window; enterprise seats meter the week and a
// monthly spend cap (a gateway's `spend_limit`, which can run past 100%).
type Cfg = { plan: string; cacheTtl: string }
type Win = { kind: string; label: string; icon: Icon }
type Icon = 'clock' | 'cal' | 'spend'
const PERSONAL: Win[] = [
  { kind: 'five_hour', label: '5h', icon: 'clock' },
  { kind: 'seven_day', label: '7d', icon: 'cal' },
]
const ENTERPRISE: Win[] = [
  { kind: 'seven_day', label: '7d', icon: 'cal' },
  { kind: 'spend_limit', label: 'mo', icon: 'spend' },
]

const isEnterprise = (cfg: Cfg, rl: Limit[]) =>
  cfg.plan === 'enterprise' || (cfg.plan !== 'personal' && rl.some(l => l.kind === 'spend_limit'))

const MIN = 60_000
const ttlOf = (cfg: Cfg, enterprise: boolean) =>
  cfg.cacheTtl === '5m' ? 5 * MIN : cfg.cacheTtl === '1h' ? 60 * MIN : enterprise ? 5 * MIN : 60 * MIN

// When the window resets: the API's own time, or for a spend cap without one, the 1st of next month.
function resetAt(win: Win, lim: Limit | undefined, t: number): number | null {
  if (lim?.resetsAt) return Date.parse(lim.resetsAt)
  if (win.kind !== 'spend_limit') return null
  const d = new Date(t)
  return new Date(d.getFullYear(), d.getMonth() + 1, 1).getTime()
}

const usd = (n: number) => `$${n.toFixed(2)}`

// The same tool with the same input this many times in one turn means Claude is going in circles.
const LOOP_REPEATS = 3
const RESERVED = new Set(['tool', 'tool_use_id', 'agentId', 'consent'])

// The intervals armed by session.start, kept so a later session.start can cancel them.
const timers: { cancel: () => void }[] = []

function hash(s: string): string {
  let h = 5381
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0
  return (h >>> 0).toString(36)
}

// The "task complete" party plays once, then Claude relaxes for a while before idling.
const RELAX_MS = 4 * 60_000
// The mascot is drawn as still frames at this interval (about 7 per second).
const FRAME_MS = 150

const GREEN = '#4cc35a'
const AMBER = '#e5a33a'
const RED = '#e5534b'
const levelColor = (p: number) => (p >= 90 ? RED : p >= 70 ? AMBER : GREEN)

function span(ms: number): string {
  if (!Number.isFinite(ms)) return '–'
  const m = Math.max(0, Math.round(ms / 60_000))
  const d = Math.floor(m / 1440)
  const h = Math.floor((m % 1440) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${m % 60}m`
  return `${m}m`
}

function clockText(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

const GLYPH: Record<Icon, string> = {
  clock: '<circle cx="15" cy="15" r="5.5" fill="none" stroke="#a0a0a0" stroke-width="1.6"/><path d="M15 12v3.4h2.6" fill="none" stroke="#a0a0a0" stroke-width="1.6" stroke-linecap="round"/>',
  cal: '<rect x="10" y="11" width="10" height="9" rx="1.5" fill="none" stroke="#a0a0a0" stroke-width="1.6"/><path d="M10 14h10M12.5 9.5v3M17.5 9.5v3" stroke="#a0a0a0" stroke-width="1.6" stroke-linecap="round"/>',
  spend: '<path d="M17.6 11.6c-.5-.8-1.5-1.3-2.6-1.3-1.5 0-2.6.8-2.6 2s1.1 1.7 2.6 2 2.6.8 2.6 2-1.1 2-2.6 2c-1.1 0-2.1-.5-2.6-1.3M15 8.8v1.5M15 19.7v1.5" fill="none" stroke="#a0a0a0" stroke-width="1.6" stroke-linecap="round"/>',
}

function ringSvg(percent: number, icon: Icon): string {
  const C = 2 * Math.PI * 12
  const p = Math.min(100, Math.max(0, percent)) / 100
  const glyph = GLYPH[icon]
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30" width="30" height="30">` +
    `<circle cx="15" cy="15" r="12" fill="none" stroke="#3a3a3a" stroke-width="2.6"/>` +
    (p > 0
      ? `<circle cx="15" cy="15" r="12" fill="none" stroke="${levelColor(percent)}" stroke-width="2.6" stroke-linecap="round" ` +
        `stroke-dasharray="${(C * p).toFixed(2)} ${C.toFixed(2)}" transform="rotate(-90 15 15)"/>`
      : '') +
    glyph +
    `</svg>`
  )
}

// A pixel hourglass: sand on top drains as the cache TTL runs out.
function hourglassSvg(frac: number): string {
  const sand = frac > 0 ? (frac > 0.2 ? GREEN : AMBER) : '#555'
  const glass = '#9a9a9a'
  let px = ''
  const r = (x: number, y: number, w: number, h: number, c: string) => {
    px += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>`
  }
  r(0, 0, 7, 1, glass)
  r(0, 8, 7, 1, glass)
  r(1, 1, 1, 2, glass); r(5, 1, 1, 2, glass); r(2, 3, 1, 1, glass); r(4, 3, 1, 1, glass)
  r(3, 4, 1, 1, glass)
  r(2, 5, 1, 1, glass); r(4, 5, 1, 1, glass); r(1, 6, 1, 2, glass); r(5, 6, 1, 2, glass)
  const top = Math.ceil(2 * Math.min(1, Math.max(0, frac)))
  if (top > 0) r(2, 3 - top, 3, top, sand)
  r(2, 7, 3, 1, sand)
  if (frac < 1 && frac > 0) r(2, 6, 3, 1, sand)
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 7 9" width="14" height="18" shape-rendering="crispEdges">${px}</svg>`
}

function ctxBarSvg(percent: number): string {
  let px = ''
  const lit = Math.round(percent / 10)
  for (let i = 0; i < 10; i++) {
    px += `<rect x="${i * 4}" y="0" width="3" height="8" fill="${i < lit ? levelColor(percent) : '#3a3a3a'}"/>`
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 39 8" width="39" height="8" shape-rendering="crispEdges">${px}</svg>`
}

async function setMood($: EngineInterface, m: Mood) {
  const t = await $.clock.now()
  await update($, moodAt, () => t)
  await update($, mood, () => m)
}

// Which scene shows `elapsed` seconds into a mood: done hands off to relax, relax to idle,
// error gives a brief puzzled beat before idling (no relax — nothing to celebrate).
function sceneFor(m: Mood, elapsed: number): { mood: Mood; t: number } {
  const relaxS = RELAX_MS / 1000
  if (m === 'done') {
    if (elapsed < DONE_SECONDS) return { mood: 'done', t: elapsed }
    return sceneFor('relax', elapsed - DONE_SECONDS)
  }
  if (m === 'error') {
    if (elapsed < ERROR_SECONDS) return { mood: 'error', t: elapsed }
    return sceneFor('idle', elapsed - ERROR_SECONDS)
  }
  if (m === 'relax' && elapsed >= relaxS) return { mood: 'idle', t: elapsed - relaxS }
  return { mood: m, t: elapsed }
}

const ALT: Partial<Record<Mood, string>> = {
  done: 'celebrating',
  relax: 'relaxing',
  error: 'puzzled',
  loop: 'going round a roller-coaster loop',
}

const kTokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${Math.round(n / 1000)}k`)

// Terminal drawing: a text mascot and block bars, since the terminal cannot show the SVGs.
const ORANGE = '#d97757'
const SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

function faceFor(m: Mood, t: number, idea = false): string {
  const f = Math.floor(t * 1000 / FRAME_MS)
  if (m === 'working') return `(o_o) ${SPIN[f % SPIN.length]}`
  if (m === 'loop') return `(@_@) ${['◜', '◝', '◞', '◟'][f % 4]}`
  if (m === 'done') return (f % 6 < 3 ? '\\(^o^)/' : '/(^o^)\\') + (idea ? ' (!)' : '')
  if (m === 'relax') return '(-‿-) z'
  if (m === 'error') return f % 10 < 5 ? '(o_O)?' : '(O_o)?'
  return f % 40 === 0 ? '(-_-)' : '(o_o)'
}

function bar(percent: number, cells = 10): string {
  const lit = Math.round((Math.min(100, Math.max(0, percent)) / 100) * cells)
  return '█'.repeat(lit) + '░'.repeat(cells - lit)
}

function cacheText(at: number | null, tNow: number, ttlMs: number): { label: string; warm: boolean; left: number } {
  const left = at === null ? 0 : ttlMs - (tNow - at)
  const warm = at !== null && left > 0
  return { label: at === null ? 'cache –' : warm ? `cache ${clockText(left)}` : 'cache cold', warm, left }
}

async function countCall($: EngineInterface, e: { tool: string; agentId?: string }) {
  if (e.agentId || (await read($, loopSince)) !== null) return
  const args = Object.fromEntries(Object.entries(e).filter(([k]) => !RESERVED.has(k)))
  const sig = `${e.tool}:${hash(JSON.stringify(args))}`
  await update($, toolCounts, c => ({ ...c, [sig]: (c[sig] ?? 0) + 1 }))
  if (((await read($, toolCounts))[sig] ?? 0) >= LOOP_REPEATS) {
    const t = await $.clock.now()
    await update($, loopSince, () => t)
  }
}

// The plan's windows and cache TTL, from the latest rate-limit reading.
async function planOf($: EngineInterface, cfg: Cfg) {
  const rl = await read($, limits)
  const enterprise = isEnterprise(cfg, rl)
  return { rl, enterprise, wins: enterprise ? ENTERPRISE : PERSONAL, ttlMs: ttlOf(cfg, enterprise) }
}

// One line in the status bar with every reading, for surfaces that draw neither band.
async function refreshStatus($: EngineInterface, cfg: Cfg) {
  const { rl, enterprise, wins, ttlMs } = await planOf($, cfg)
  const c = await read($, ctx)
  const at = await read($, cacheAt)
  const spent = await read($, cost)
  const t = await $.clock.now()
  const pct = (k: string) => {
    const l = rl.find(x => x.kind === k)
    return l ? `${Math.round(l.percentUsed)}%` : '–'
  }
  const parts = [
    ...wins.map(w => `${w.label} ${pct(w.kind)}`),
    ...(enterprise && spent !== null ? [usd(spent)] : []),
    cacheText(at, t, ttlMs).label,
    c?.percent === undefined ? 'ctx –' : `ctx ${c.percent}%`,
  ]
  $.ui.status(`(o_o) ${parts.join(' · ')}`)
}

export const register: Register = (on, options) => {
  const cfg: Cfg = { plan: String(options.plan ?? 'auto'), cacheTtl: String(options.cacheTtl ?? 'auto') }

  on('session.start', async ($, e, next) => {
    // session.start can fire again for the same module (an enable, a worker respawn):
    // drop the previous timers so the intervals never stack up.
    for (const timer of timers.splice(0)) timer.cancel()

    const u = await $.session.usage()
    await update($, ctx, () => u.context)
    await update($, limits, () => u.rateLimits)
    await update($, cost, () => u.cost?.usd ?? null)
    const t0 = await $.clock.now()
    await update($, minute, () => t0)

    // Keep "resets in" fresh, and tick the cache countdown while it is warm.
    timers.push($.clock.every(60_000, async () => {
      const t = await $.clock.now()
      await update($, minute, () => t)
      await refreshStatus($, cfg)
    }))
    await update($, moodAt, () => t0)
    timers.push($.clock.every(FRAME_MS, async () => {
      const t = await $.clock.now()
      await update($, frame, () => t)
    }))
    timers.push($.clock.every(1_000, async () => {
      const at = await read($, cacheAt)
      if (at === null) return
      const t = await $.clock.now()
      const { ttlMs } = await planOf($, cfg)
      // Tick while warm, and always once more after expiry: a late tick (the machine
      // slept) must still flip the label to "cold" instead of freezing a stale countdown.
      const shownWarm = (await read($, now)) - at < ttlMs
      if (t - at < ttlMs + 2_000 || shownWarm) {
        await update($, now, () => t)
        await refreshStatus($, cfg)
      }
    }))

    await refreshStatus($, cfg)
    $.ui.toast('clawd-hud loaded')
    return next(e)
  })

  // Each response refreshes the prompt cache and reports the live usage.
  on('session.measure', async ($, e, next) => {
    await update($, ctx, () => e.context)
    if (e.rateLimits.length) await update($, limits, () => e.rateLimits)
    if (e.cost) await update($, cost, () => e.cost?.usd ?? null)
    if (e.changed.includes('context')) {
      const t = await $.clock.now()
      await update($, cacheAt, () => t)
      await update($, now, () => t)
    }
    await refreshStatus($, cfg)
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    await update($, toolCounts, () => ({}))
    await update($, loopSince, () => null)
    await setMood($, 'working')
    return next(e)
  })

  // Counts each main-loop tool call by its input; a repeat past LOOP_REPEATS starts the coaster.
  // tool.call gates every tool, so the counting is best-effort: a failure must never block the call.
  on('tool.call', async ($, e, next) => {
    await countCall($, e)
    return next(e)
  }).catch(($, e, next) => next(e))

  // Task complete: the party plays once, then Claude relaxes, then idles. An error gets
  // its own puzzled beat instead of silently idling, so a failure is visible at a glance.
  // The hand-offs are worked out from the clock on each frame (see sceneFor), so no timer can be lost.
  on('turn.complete', async ($, e, next) => {
    if (e.agentId) return next(e)
    const t = await $.clock.now()
    const startedAt = (await read($, mood)) === 'working' ? await read($, moodAt) : t
    const solved = !e.isAborted && e.reason === 'answer'
    await update($, eureka, () => solved && t - startedAt >= HARD_SECONDS * 1000)
    await update($, loopSince, () => null)
    await setMood($, e.isAborted ? 'idle' : solved ? 'done' : 'error')
    return next(e)
  })

  // The band above the prompt: two usage rings on the left, the mascot on the right.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const ui = $.ui.resolve(e)
    const { Box, Text } = ui
    const { rl, enterprise, wins } = await planOf($, cfg)
    const spent = enterprise ? await read($, cost) : null
    const t = await read($, minute)
    const stored = await read($, mood)
    const m: Mood = e.props.isWorking ? 'working' : stored === 'working' ? 'idle' : stored
    const tFrame = await read($, frame)
    // When the band's mood is not the stored one (the UI says "working" before turn.start
    // lands, or the turn ended before turn.complete ran) there is no start time: run a
    // free clock that stays under HARD_SECONDS, never the raw epoch (which reads as a
    // turn that has run for decades and jumps straight to the smoke break).
    const elapsed = m === stored ? (tFrame - (await read($, moodAt))) / 1000 : (tFrame / 1000) % HARD_SECONDS
    const loopAt = await read($, loopSince)
    const { mood: shownMood, t: sceneT } =
      e.props.isWorking && loopAt !== null
        ? { mood: 'loop' as Mood, t: Math.max(0, (tFrame - loopAt) / 1000) }
        : sceneFor(m, Math.max(0, elapsed))
    const idea = shownMood === 'done' && (await read($, eureka))
    const shown = wins.map(w => {
      const lim = rl.find(l => l.kind === w.kind)
      const at = t ? resetAt(w, lim, t) : null
      return { ...w, lim, resets: lim && at !== null && t ? `resets in ${span(at - t)}` : 'waiting for a reading' }
    })
    const pctText = (lim: Limit | undefined) => (lim ? `${Math.round(lim.percentUsed)}%` : '–')

    if (e.surface !== 'desktop' && e.surface !== 'vscode') {
      return (
        <Box flexDirection="row" flexWrap="wrap" gap={3}>
          <Text bold color={ORANGE}>{faceFor(shownMood, sceneT, idea)}</Text>
          {shown.map(s => (
            <Box key={s.kind} flexDirection="row" gap={1}>
              <Text bold>{s.label}</Text>
              <Text color={s.lim ? levelColor(s.lim.percentUsed) : undefined} dimColor={!s.lim}>{bar(s.lim?.percentUsed ?? 0)}</Text>
              <Text bold>{pctText(s.lim)}</Text>
              <Text dimColor>{s.resets}</Text>
            </Box>
          ))}
          {spent !== null ? <Text bold>{`${usd(spent)} this session`}</Text> : null}
        </Box>
      )
    }
    const { Svg } = $.ui.resolve(e as typeof e & { surface: 'desktop' })

    return (
      <Box flexDirection="row" alignItems="center" justifyContent="space-between" paddingX={1}>
        <Box flexDirection="row" alignItems="center" gap={3}>
          {shown.map(s => (
            <Box key={s.kind} flexDirection="row" alignItems="center" gap={1}>
              <Svg source={ringSvg(s.lim?.percentUsed ?? 0, s.icon)} alt={`${s.label} usage ring`} width={30} height={30} />
              <Text bold>{pctText(s.lim)}</Text>
              <Text dimColor>{`${s.label} · ${s.resets}`}</Text>
            </Box>
          ))}
          {spent !== null ? (
            <Box flexDirection="row" alignItems="center" gap={1}>
              <Text bold>{usd(spent)}</Text>
              <Text dimColor>this session</Text>
            </Box>
          ) : null}
        </Box>
        <Svg
          source={sceneSvg(shownMood, sceneT, idea)}
          alt={`Claude is ${idea ? 'having a eureka moment' : ALT[shownMood] ?? shownMood}`}
          width={SCENE_WIDTH}
          height={SCENE_HEIGHT}
        />
      </Box>
    )
  })

  // Beside the model picker: prompt-cache countdown and context fill.
  on('ui.render', { component: 'SessionMode' }, async ($, e, next) => {
    const { Box, Text } = $.ui.resolve(e)
    const { ttlMs } = await planOf($, cfg)
    const at = await read($, cacheAt)
    const tNow = await read($, now)
    const c = await read($, ctx)
    const left = at === null ? 0 : ttlMs - (tNow - at)
    const warm = at !== null && left > 0
    const cacheLabel = at === null ? 'cache –' : warm ? `cache ${clockText(left)}` : 'cache cold'
    const cacheColor = !warm ? undefined : left < 60_000 ? AMBER : GREEN
    const pct = c?.percent
    const ctxLabel =
      pct === undefined ? 'ctx –' : `ctx ${pct}%${c?.tokens ? ` · ${kTokens(c.tokens)}/${kTokens(c.window)}` : ''}`
    const modes = e.props.modes.join(' & ')

    if (e.surface !== 'desktop' && e.surface !== 'vscode') {
      return (
        <Box flexDirection="row" gap={1}>
          <Text color={cacheColor} dimColor={!warm}>{cacheLabel}</Text>
          <Text dimColor>·</Text>
          <Text color={pct === undefined ? undefined : levelColor(pct)} dimColor={pct === undefined}>{bar(pct ?? 0, 8)}</Text>
          <Text dimColor>{ctxLabel}</Text>
          {modes ? <Text dimColor>{`· ${modes}`}</Text> : null}
        </Box>
      )
    }
    const { Svg } = $.ui.resolve(e as typeof e & { surface: 'desktop' })

    return (
      <Box flexDirection="row" alignItems="center" gap={1}>
        <Svg source={hourglassSvg(warm ? left / ttlMs : 0)} alt="prompt cache timer" width={14} height={18} />
        <Text color={cacheColor} dimColor={!warm}>{cacheLabel}</Text>
        <Text dimColor>·</Text>
        <Svg source={ctxBarSvg(pct ?? 0)} alt="context used" width={39} height={8} />
        <Text dimColor>{ctxLabel}</Text>
        {modes ? <Text dimColor>{`· ${modes}`}</Text> : null}
      </Box>
    )
  })
}
