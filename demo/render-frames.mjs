// Renders the demo GIF's frames from the plugin's real drawing code.
//
//   cd demo && npm install && node render-frames.mjs && python make-gif.py
//
// The spark comes straight from hooks/scene.ts and the batteries, bolt and capsule from
// hooks/gauges.ts (Node strips the types), set in a mock Claude Code window. Frames land in
// demo/frames/*.png; make-gif.py stitches them into ../assets/clawd-hud.gif.

import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Resvg } from '@resvg/resvg-js'
import { HARD_SECONDS, SCENE_HEIGHT, SCENE_WIDTH, sceneSvg } from '../plugins/clawd-hud/hooks/scene.ts'
import { LOW, OK, batterySvg, boltSvg, pillSvg } from '../plugins/clawd-hud/hooks/gauges.ts'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, 'frames')
rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })

const FRAME_S = 0.125 // the plugin's FRAME_MS
const W = 960
const H = 330
const FONT = 'Consolas, Menlo, monospace'

// An SVG string dropped in at (x, y), optionally resized.
const place = (svg, x, y, w, h) => {
  let s = svg.replace('<svg ', `<svg x="${x}" y="${y}" `)
  if (w) s = s.replace(/width="\d+" height="\d+"/, `width="${w}" height="${h}"`)
  return s
}
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const text = (x, y, s, { size = 14, fill = '#d0d6f0', weight = 'normal', anchor = 'start' } = {}) =>
  `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${esc(s)}</text>`

// ---- the storyboard: which scene, what the transcript says, which plan's meters ----
const PROMPT = 'refactor the auth module and add tests'
const DONE_LOG = ['✔ Refactored auth, 43 tests passing']
const beats = [
  { mood: 'idle', t0: 0, frames: 20, note: 'drifting while you think', typing: true },
  { mood: 'idle', t0: 12, frames: 16, note: 'juggling', typing: true, typeFrom: 20 },
  { mood: 'working', t0: 0, frames: 20, note: 'at the terminal', log: ['● Read(src/auth/session.ts)', '● Edit(src/auth/session.ts)'] },
  { mood: 'working', t0: 18, frames: 18, note: 'sending out sub-agents', log: ['● Task(write unit tests)', '● Task(update docs)'] },
  { mood: 'working', t0: HARD_SECONDS, frames: 22, note: 'hard task: smoke break', log: ['● Edit(src/auth/token.ts)', '● Bash(npm test)'] },
  { mood: 'loop', t0: 0, frames: 22, note: 'same call 3x: stuck in a loop', log: ['● Bash(npm test)  ×3', '  ⎿ 2 failed  (again)'] },
  { mood: 'done', t0: 0, frames: 40, note: 'fireworks + eureka bulb', eureka: true, log: DONE_LOG },
  { mood: 'relax', t0: 0, frames: 18, note: 'stargazing', log: DONE_LOG },
  { mood: 'relax', t0: 16, frames: 18, note: 'pool float', log: DONE_LOG },
  { mood: 'relax', t0: 32, frames: 18, note: 'cocoa by the window', log: DONE_LOG },
  { mood: 'working', t0: 0, frames: 20, note: 'enterprise seat: weekly + monthly spend', enterprise: true, log: ['● Read(billing/report.ts)'] },
  { mood: 'error', t0: 0, frames: 24, note: 'API error: a little storm', log: ['✘ API Error: overloaded'] },
]
const MOOD_COLOR = { idle: '#a7b0d6', working: '#5ad1ff', loop: '#9d7bff', done: '#6be38b', relax: '#ffb547', error: '#ff5a5a' }

const total = beats.reduce((n, b) => n + b.frames, 0)
let k = 0
let sim = 0
let cacheAt = null

for (const [bi, b] of beats.entries()) {
  if (b.mood === 'working' && cacheAt === null) cacheAt = sim
  if (b.t0 === HARD_SECONDS) sim += 90
  const ttl = b.enterprise ? 300 : 3600
  for (let i = 0; i < b.frames; i++, k++) {
    const t = b.t0 + i * FRAME_S
    sim += FRAME_S
    const progress = k / total
    const ctxPct = cacheAt === null ? null : Math.min(78, 18 + Math.round(progress * 60))
    const left = cacheAt === null ? null : ttl - ((sim - cacheAt) % ttl)

    let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`
    svg += `<rect width="${W}" height="${H}" fill="#0c0f1d"/>`
    svg += `<rect width="${W}" height="30" fill="#1a1f36"/>`
    svg += text(16, 20, '✦ clawd-hud', { size: 13, fill: '#ffb547', weight: 'bold' })

    const badge = `${b.mood}  ·  ${b.note}`
    svg += text(W - 18, 61, badge, { size: 14, fill: MOOD_COLOR[b.mood], weight: 'bold', anchor: 'end' })

    if (b.typing) {
      svg += text(24, 62, 'What should we build today?', { size: 14, fill: '#6b7390' })
    } else {
      svg += text(24, 62, `> ${PROMPT}`, { size: 15, fill: '#eef1ff' })
      ;(b.log ?? []).forEach((line, j) => {
        const c = line.startsWith('✔') ? OK : line.startsWith('✘') ? '#ff5a5a' : line.startsWith('  ⎿') ? '#6b7390' : '#ffb547'
        svg += text(24, 88 + j * 22, line, { size: 14, fill: c })
      })
    }

    // The band: the spark on the left, batteries beside it.
    const bandY = 136
    svg += `<rect x="12" y="${bandY}" width="${W - 24}" height="92" rx="6" fill="#151a30"/>`
    const sw = Math.round(SCENE_WIDTH * 1.3)
    const sh = Math.round(SCENE_HEIGHT * 1.3)
    svg += place(sceneSvg(b.mood, t, !!b.eureka), 24, bandY + 7, sw, sh)
    const meters = b.enterprise
      ? [
          { label: '7d', used: 41 + Math.round(progress * 4), reset: 'resets in 4d 7h' },
          { label: 'mo', used: 63, reset: 'resets in 22d 11h' },
        ]
      : [
          { label: '5h', used: 34 + Math.round(progress * 9), reset: `resets in 2h ${41 - Math.floor(progress * 30)}m` },
          { label: '7d', used: 12 + Math.round(progress * 2), reset: 'resets in 4d 7h' },
        ]
    meters.forEach((m, j) => {
      const x = 24 + sw + 28 + j * 250
      svg += place(batterySvg(100 - m.used), x, bandY + 24)
      svg += text(x + 58, bandY + 38, `${m.label} ${100 - m.used}% left`, { size: 15, fill: '#eef1ff', weight: 'bold' })
      svg += text(x + 58, bandY + 58, m.reset, { size: 12, fill: '#6b7390' })
    })
    if (b.enterprise) svg += text(24 + sw + 28, bandY + 82, '$1.84 this session', { size: 13, fill: '#eef1ff', weight: 'bold' })

    const promptY = 240
    svg += `<rect x="12" y="${promptY}" width="${W - 24}" height="44" rx="6" fill="none" stroke="#2c3354" stroke-width="1.5"/>`
    if (b.typing) {
      const n = Math.min(PROMPT.length, Math.floor(((b.typeFrom ?? 0) + i) * 1.6))
      svg += text(28, promptY + 28, `> ${PROMPT.slice(0, n)}${Math.floor(k / 3) % 2 === 0 ? '▌' : ' '}`, { size: 15, fill: '#eef1ff' })
    } else {
      svg += text(28, promptY + 28, '>', { size: 15, fill: '#6b7390' })
    }

    // Beside the model picker: the cache bolt and the context capsule.
    const rowY = 310
    svg += text(24, rowY, 'Opus', { size: 13, fill: '#a7b0d6' })
    const warm = left !== null && left > 0
    const color = !warm ? '#59618a' : left < 60 ? LOW : OK
    const cacheLabel = left === null ? 'cache –' : `cache ${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')}`
    let x = 80
    svg += place(boltSvg(color), x, rowY - 13)
    x += 16
    svg += text(x, rowY, cacheLabel, { size: 13, fill: color })
    x += cacheLabel.length * 7.3 + 10
    svg += text(x, rowY, '·', { size: 13, fill: '#59618a' })
    x += 16
    svg += place(pillSvg(ctxPct ?? 0), x, rowY - 9)
    x += 50
    svg += text(x, rowY, ctxPct === null ? 'ctx –' : `ctx ${ctxPct}% · ${ctxPct * 2}k/200k`, { size: 13, fill: '#a7b0d6' })
    svg += text(W - 24, rowY, `${bi + 1}/${beats.length}`, { size: 12, fill: '#3a4060', anchor: 'end' })

    svg += `</svg>`
    const png = new Resvg(svg, { font: { loadSystemFonts: true, defaultFontFamily: 'Consolas' } }).render().asPng()
    writeFileSync(join(out, `${String(k).padStart(4, '0')}.png`), png)
  }
}
console.log(`rendered ${k} frames to ${out}`)
