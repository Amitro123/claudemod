// Renders the demo GIF's frames from the plugin's real scene code.
//
//   cd demo && npm install && node render-frames.mjs && python make-gif.py
//
// Every mascot frame comes straight from hooks/scene.ts (Node strips the types), framed in a
// mock Claude Code window with the usage rings, cache hourglass and context meter the plugin
// draws. Frames land in demo/frames/*.png; make-gif.py stitches them into clawd-hud.gif.

import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Resvg } from '@resvg/resvg-js'
import { sceneSvg, HARD_SECONDS } from '../plugins/clawd-hud/hooks/scene.ts'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, 'frames')
rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })

const FRAME_S = 0.15 // the plugin's FRAME_MS
const W = 960
const H = 330
const FONT = 'Consolas, Menlo, monospace'

// ---- the same little drawings register.tsx makes ----
const GREEN = '#4cc35a'
const AMBER = '#e5a33a'
const RED = '#e5534b'
const levelColor = p => (p >= 90 ? RED : p >= 70 ? AMBER : GREEN)

function ring(percent, icon, x, y, s) {
  const C = 2 * Math.PI * 12
  const p = Math.min(100, Math.max(0, percent)) / 100
  const glyph =
    icon === 'clock'
      ? '<circle cx="15" cy="15" r="5.5" fill="none" stroke="#a0a0a0" stroke-width="1.6"/><path d="M15 12v3.4h2.6" fill="none" stroke="#a0a0a0" stroke-width="1.6" stroke-linecap="round"/>'
      : '<rect x="10" y="11" width="10" height="9" rx="1.5" fill="none" stroke="#a0a0a0" stroke-width="1.6"/><path d="M10 14h10M12.5 9.5v3M17.5 9.5v3" stroke="#a0a0a0" stroke-width="1.6" stroke-linecap="round"/>'
  return (
    `<g transform="translate(${x} ${y}) scale(${s})">` +
    `<circle cx="15" cy="15" r="12" fill="none" stroke="#3a3a3a" stroke-width="2.6"/>` +
    (p > 0
      ? `<circle cx="15" cy="15" r="12" fill="none" stroke="${levelColor(percent)}" stroke-width="2.6" stroke-linecap="round" stroke-dasharray="${(C * p).toFixed(2)} ${C.toFixed(2)}" transform="rotate(-90 15 15)"/>`
      : '') +
    glyph +
    `</g>`
  )
}

function hourglass(frac, x, y, s) {
  const sand = frac > 0 ? (frac > 0.2 ? GREEN : AMBER) : '#555'
  const g = '#9a9a9a'
  let px = ''
  const r = (a, b, w, h, c) => (px += `<rect x="${a}" y="${b}" width="${w}" height="${h}" fill="${c}"/>`)
  r(0, 0, 7, 1, g); r(0, 8, 7, 1, g)
  r(1, 1, 1, 2, g); r(5, 1, 1, 2, g); r(2, 3, 1, 1, g); r(4, 3, 1, 1, g)
  r(3, 4, 1, 1, g)
  r(2, 5, 1, 1, g); r(4, 5, 1, 1, g); r(1, 6, 1, 2, g); r(5, 6, 1, 2, g)
  const top = Math.ceil(2 * frac)
  if (top > 0) r(2, 3 - top, 3, top, sand)
  r(2, 7, 3, 1, sand)
  if (frac < 1 && frac > 0) r(2, 6, 3, 1, sand)
  return `<g transform="translate(${x} ${y}) scale(${s})" shape-rendering="crispEdges">${px}</g>`
}

function ctxBar(percent, x, y, s) {
  let px = ''
  const lit = Math.round(percent / 10)
  for (let i = 0; i < 10; i++) px += `<rect x="${i * 4}" y="0" width="3" height="8" fill="${i < lit ? levelColor(percent) : '#3a3a3a'}"/>`
  return `<g transform="translate(${x} ${y}) scale(${s})" shape-rendering="crispEdges">${px}</g>`
}

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const text = (x, y, s, { size = 14, fill = '#d0d0d0', weight = 'normal', anchor = 'start' } = {}) =>
  `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${esc(s)}</text>`

// The scene, scaled from its 100x18 grid to 4x and dropped into the band.
const SCENE_SCALE = 4
function placedScene(mood, t, eureka, x, y) {
  const svg = sceneSvg(mood, t, eureka)
  return svg.replace(/^<svg ([^>]*)width="\d+" height="\d+"/, `<svg $1x="${x}" y="${y}" width="${100 * SCENE_SCALE}" height="${18 * SCENE_SCALE}"`)
}

const clock = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// ---- the storyboard ----
// Each beat: which mood/scene time to show, what the transcript says, and the readings.
const PROMPT = 'refactor the auth module and add tests'
const beats = [
  { mood: 'idle', t0: 0, frames: 18, label: 'idle', note: 'sweeping up while you think', typing: true },
  { mood: 'idle', t0: 16, frames: 12, label: 'idle', note: 'scrolling the phone', typing: true, typeFrom: 18 },
  { mood: 'working', t0: 0, frames: 18, label: 'working', note: 'typing on the laptop', log: ['● Read(src/auth/session.ts)', '● Edit(src/auth/session.ts)'] },
  { mood: 'working', t0: 12, frames: 16, label: 'working', note: 'dispatching sub-agents', log: ['● Task(write unit tests)', '● Task(update docs)'] },
  { mood: 'working', t0: 30, frames: 16, label: 'working', note: 'analysing the results', log: ['● Bash(npm test)', '  ⎿ 41 passed, 2 failed'] },
  { mood: 'working', t0: HARD_SECONDS, frames: 18, label: 'working > 90s', note: 'hard task: smoke break', log: ['● Edit(src/auth/token.ts)', '● Bash(npm test)'] },
  { mood: 'loop', t0: 0, frames: 18, label: 'loop', note: 'same tool call 3x: stuck in a loop', log: ['● Bash(npm test)  ×3', '  ⎿ 2 failed  (again)'] },
  { mood: 'done', t0: 0, frames: 34, label: 'done', note: 'task complete + eureka bulb', eureka: true, log: ['✔ Refactored auth, 43 tests passing'] },
  { mood: 'relax', t0: 0, frames: 14, label: 'relax', note: 'sunset chair', log: ['✔ Refactored auth, 43 tests passing'] },
  { mood: 'relax', t0: 8, frames: 14, label: 'relax', note: 'night fishing', log: ['✔ Refactored auth, 43 tests passing'] },
  { mood: 'relax', t0: 24, frames: 14, label: 'relax', note: 'campfire', log: ['✔ Refactored auth, 43 tests passing'] },
  { mood: 'relax', t0: 40, frames: 14, label: 'relax', note: 'sunset drive', log: ['✔ Refactored auth, 43 tests passing'] },
  { mood: 'error', t0: 0, frames: 20, label: 'error', note: 'API error: a puzzled beat', log: ['✘ API Error: overloaded'] },
]
const MOOD_COLOR = { idle: '#8a8a8a', working: '#5a8fe6', loop: '#9b6be0', done: '#4cc35a', relax: '#e5a33a', error: '#e5534b' }

const total = beats.reduce((n, b) => n + b.frames, 0)
let k = 0
let sim = 0 // seconds of session time, for the cache countdown and usage drift
let cacheAt = null

for (const [bi, b] of beats.entries()) {
  if (b.mood === 'working' && cacheAt === null) cacheAt = sim
  if (b.mood === 'working' && b.t0 === HARD_SECONDS) sim += 90
  for (let i = 0; i < b.frames; i++, k++) {
    const t = b.t0 + i * FRAME_S
    sim += FRAME_S
    const progress = k / total
    const p5 = 34 + Math.round(progress * 9)
    const p7 = 12 + Math.round(progress * 2)
    const ctxPct = cacheAt === null ? null : Math.min(78, 18 + Math.round(progress * 60))
    const ttl = 3600
    const left = cacheAt === null ? null : ttl - (sim - cacheAt)

    let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`
    svg += `<rect width="${W}" height="${H}" fill="#181818"/>`
    // window chrome
    svg += `<rect width="${W}" height="30" fill="#262626"/>`
    svg += `<circle cx="18" cy="15" r="6" fill="#e5534b"/><circle cx="38" cy="15" r="6" fill="#e5a33a"/><circle cx="58" cy="15" r="6" fill="#4cc35a"/>`
    svg += text(W / 2, 20, 'Claude Code  ·  clawd-hud plugin', { size: 13, fill: '#9a9a9a', anchor: 'middle' })

    // mood badge
    const badge = `${b.label}  ·  ${b.note}`
    svg += `<rect x="${W - 24 - badge.length * 8.4}" y="44" width="${badge.length * 8.4 + 12}" height="24" rx="12" fill="${MOOD_COLOR[b.mood]}" opacity="0.18"/>`
    svg += text(W - 18, 61, badge, { size: 14, fill: MOOD_COLOR[b.mood], weight: 'bold', anchor: 'end' })

    // transcript
    const started = !b.typing
    if (started) {
      svg += text(24, 62, `> ${PROMPT}`, { size: 15, fill: '#e8e8e8' })
      ;(b.log ?? []).forEach((line, j) => {
        const c = line.startsWith('✔') ? GREEN : line.startsWith('✘') ? RED : line.startsWith('  ⎿') ? '#8a8a8a' : '#d97757'
        svg += text(24, 88 + j * 22, line, { size: 14, fill: c })
      })
    } else {
      svg += text(24, 62, 'Welcome back! What should we build today?', { size: 14, fill: '#8a8a8a' })
    }

    // the band above the prompt: rings on the left, the mascot on the right
    const bandY = 140
    svg += `<rect x="12" y="${bandY}" width="${W - 24}" height="88" rx="8" fill="#212121"/>`
    const rings = [
      { label: '5h', pct: p5, icon: 'clock', reset: `resets in ${2 - Math.floor(progress * 1.2)}h ${41 - Math.floor(progress * 30)}m` },
      { label: '7d', pct: p7, icon: 'cal', reset: 'resets in 4d 7h' },
    ]
    rings.forEach((r, j) => {
      const x = 28 + j * 230
      svg += ring(r.pct, r.icon, x, bandY + 22, 1.5)
      svg += text(x + 54, bandY + 44, `${r.pct}%`, { size: 15, fill: '#f0f0f0', weight: 'bold' })
      svg += text(x + 54, bandY + 64, `${r.label} · ${r.reset}`, { size: 12, fill: '#8a8a8a' })
    })
    svg += placedScene(b.mood, t, !!b.eureka, W - 24 - 400, bandY + 8)

    // prompt box
    const promptY = 240
    svg += `<rect x="12" y="${promptY}" width="${W - 24}" height="44" rx="8" fill="none" stroke="#4a4a4a" stroke-width="1.5"/>`
    if (b.typing) {
      const from = b.typeFrom ?? 0
      const n = Math.min(PROMPT.length, Math.floor((from + i) * 1.6))
      const cursor = Math.floor(k / 3) % 2 === 0 ? '▌' : ' '
      svg += text(28, promptY + 28, `> ${PROMPT.slice(0, n)}${cursor}`, { size: 15, fill: '#e8e8e8' })
    } else {
      svg += text(28, promptY + 28, '>', { size: 15, fill: '#8a8a8a' })
    }

    // beside the model picker: cache hourglass + context meter
    const rowY = 310
    svg += text(24, rowY, 'Opus', { size: 13, fill: '#9a9a9a' })
    const warm = left !== null && left > 0
    const cacheLabel = left === null ? 'cache –' : warm ? `cache ${clock(left)}` : 'cache cold'
    let x = 80
    svg += hourglass(warm ? left / ttl : 0, x, rowY - 15, 2)
    x += 22
    svg += text(x, rowY, cacheLabel, { size: 13, fill: warm ? (left < 60 ? AMBER : GREEN) : '#777' })
    x += cacheLabel.length * 7.3 + 10
    svg += text(x, rowY, '·', { size: 13, fill: '#777' })
    x += 16
    svg += ctxBar(ctxPct ?? 0, x, rowY - 11, 1.5)
    x += 66
    const ctxLabel = ctxPct === null ? 'ctx –' : `ctx ${ctxPct}% · ${Math.round(ctxPct * 2)}k/200k`
    svg += text(x, rowY, ctxLabel, { size: 13, fill: '#8a8a8a' })
    svg += text(W - 24, rowY, `${bi + 1}/${beats.length}`, { size: 12, fill: '#555', anchor: 'end' })

    svg += `</svg>`
    const png = new Resvg(svg, { font: { loadSystemFonts: true, defaultFontFamily: 'Consolas' } }).render().asPng()
    writeFileSync(join(out, `${String(k).padStart(4, '0')}.png`), png)
  }
}
console.log(`rendered ${k} frames to ${out}`)
