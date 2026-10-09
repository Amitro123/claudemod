// Scenes for the spark mascot. `sceneSvg` paints ONE frame of a mood, `t` seconds into it,
// on an 88x20 pixel stage drawn at 3x. Every motion is a plain function of `t`, so a redraw
// lands on the same frame and never restarts an animation.

import type { Mood } from '../types'

const W = 88
const H = 20
const SCALE = 3
const FLOOR = 17

export const SCENE_WIDTH = W * SCALE
export const SCENE_HEIGHT = H * SCALE
export const DONE_SECONDS = 6.5
export const ERROR_SECONDS = 3.2
// A turn that runs this long is a hard task: smoke breaks while on it, a lightbulb when it lands.
export const HARD_SECONDS = 90

const SKY = '#11152a'
const INK: Record<string, string> = {
  A: '#ffb547', // spark
  a: '#d9822b', // spark, shaded
  H: '#fff1c2', // spark, lit
  s: '#8a90a8', // spark, gone gray
  S: '#5d637c',
  e: '#2b1606', // eyes
  k: '#0a0c18',
  N: '#1c2240',
  d: '#2c3354',
  L: '#59618a',
  l: '#a7b0d6',
  w: '#f4f6ff',
  y: '#ffe066',
  o: '#ff8a3d',
  r: '#ff5a5a',
  m: '#ff6fae',
  c: '#5ad1ff',
  C: '#2b7cb3',
  g: '#6be38b',
  G: '#2f8f55',
  v: '#9d7bff',
  b: '#8a5a33',
  B: '#5c3a20',
}

// ---------- drawing ----------

class Canvas {
  private parts: string[] = []

  rect(x: number, y: number, w: number, h: number, c: string) {
    if (w <= 0 || h <= 0) return
    this.parts.push(`<rect x="${Math.round(x)}" y="${Math.round(y)}" width="${w}" height="${h}" fill="${INK[c] ?? c}"/>`)
  }

  dot(x: number, y: number, c: string) {
    this.rect(x, y, 1, 1, c)
  }

  // ASCII art, one char per pixel ('.' is empty); `swap` recolors chars as it draws.
  art(rows: readonly string[], x: number, y: number, swap: Record<string, string> = {}) {
    rows.forEach((row, j) => {
      for (let i = 0; i < row.length; ) {
        const ch = row[i] ?? '.'
        let k = i + 1
        while (k < row.length && row[k] === ch) k++
        if (ch !== '.') this.rect(x + i, y + j, k - i, 1, swap[ch] ?? ch)
        i = k
      }
    })
  }

  toString() {
    return this.parts.join('')
  }
}

// ---------- motion ----------

const TAU = Math.PI * 2
const osc = (t: number, period: number, amp: number, phase = 0) => Math.round(Math.sin((t / period + phase) * TAU) * amp)
const tick = (t: number, fps: number, n: number) => ((Math.floor(t * fps) % n) + n) % n

// A stable pseudo-random number in [0, 1) for an integer seed.
function noise(n: number): number {
  let x = Math.imul((n | 0) ^ 0x9e3779b9, 0x85ebca6b)
  x ^= x >>> 13
  x = Math.imul(x, 0xc2b2ae35)
  x ^= x >>> 16
  return (x >>> 0) / 4294967296
}

// Plays each scene for `each` seconds, in turn.
function rotate(t: number, each: number, scenes: ((t: number) => void)[]) {
  scenes[Math.floor(Math.max(0, t) / each) % scenes.length]?.(t)
}

// ---------- the spark ----------

// 15x11: a four-point star; its core (rows 4-8) carries the face.
const PLUS = [
  '.......A.......',
  '.......A.......',
  '......AHA......',
  '......AAA......',
  '.....HAAAA.....',
  '...AHAAAAAAA...',
  'AAAAAAAAAAAAAAa',
  '...AAAAAAAAa...',
  '.....AAAAa.....',
  '......aAa......',
  '.......a.......',
]
// The same star turned 45 degrees, for twinkles and spins.
const CROSS = [
  '...............',
  '..A.........A..',
  '...A.......A...',
  '....A.....A....',
  '.....HAAAA.....',
  '...AHAAAAAAA...',
  '...AAAAAAAAA...',
  '...AAAAAAAAa...',
  '.....AAAAa.....',
  '....a.....a....',
  '...a.......a...',
]
const GRAY = { A: 's', a: 'S', H: 'l' }

type Face = 'calm' | 'happy' | 'focus' | 'sleepy' | 'dizzy' | 'sad' | 'wow' | 'shades'

function face(cv: Canvas, x: number, y: number, f: Face, t: number) {
  switch (f) {
    case 'calm':
      if (t % 3.7 < 0.16) cv.art(['e...e'], x + 5, y + 6)
      else cv.art(['e...e', 'e...e'], x + 5, y + 5)
      return
    case 'happy':
      cv.art(['.e...e.', 'e.e.e.e'], x + 4, y + 5)
      cv.dot(x + 3, y + 7, 'm')
      cv.dot(x + 11, y + 7, 'm')
      return
    case 'focus':
      cv.art(['aa...aa', 'ee...ee'], x + 4, y + 5)
      return
    case 'sleepy':
      cv.art(['ee...ee'], x + 4, y + 6)
      return
    case 'dizzy':
      cv.art(['e.e.e.e', '.e...e.', 'e.e.e.e'], x + 4, y + 5)
      return
    case 'sad':
      cv.art(['.e...e.', '.e...e.', '...e...', '..e.e..'], x + 4, y + 5)
      return
    case 'wow':
      cv.art(['.e...e.', '.e...e.', '...e...'], x + 4, y + 5)
      return
    case 'shades':
      cv.art(['kwkk.kwkk', 'kkkkkkkkk'], x + 3, y + 5)
      return
  }
}

type SparkOpts = { face?: Face; turned?: boolean; gray?: boolean }

function spark(cv: Canvas, x: number, y: number, t: number, o: SparkOpts = {}) {
  cv.art(o.turned ? CROSS : PLUS, x, y, o.gray ? GRAY : {})
  face(cv, x, y, o.face ?? 'calm', t)
}

// 7x7 helper sparks: sub-agents, the coaster rider.
const MINI = ['...A...', '..AAA..', '.AeAeA.', 'AAAAAAa', '.AAAAa.', '..AAa..', '...a...']

// ---------- stage ----------

// Night sky with a few far stars, and a horizon floor whose lines run off to a vanishing point.
function stage(cv: Canvas, t: number) {
  for (let i = 0; i < 16; i++) {
    const x = Math.floor(noise(i) * W)
    const y = Math.floor(noise(i + 40) * 11)
    cv.dot(x, y, tick(t + noise(i + 80) * 9, 1.5, 6) === 0 ? 'd' : 'L')
  }
  cv.rect(0, FLOOR, W, 1, 'L')
  for (let k = -7; k <= 7; k++) {
    cv.dot(W / 2 + k * 6, FLOOR + 1, 'd')
    cv.dot(W / 2 + k * 9, FLOOR + 2, 'd')
  }
}

function monitor(cv: Canvas, x: number, y: number, t: number, on = true) {
  cv.rect(x, y, 14, 9, 'L')
  cv.rect(x + 1, y + 1, 12, 7, 'k')
  cv.rect(x + 6, y + 9, 2, 1, 'L')
  cv.rect(x + 4, y + 10, 6, 1, 'L')
  if (!on) {
    cv.art(['www', '..w', '.w.', 'www'], x + 5, y + 2)
    return
  }
  const scroll = Math.floor(t * 3)
  for (let r = 0; r < 6; r++) {
    const line = scroll + r
    const indent = Math.floor(noise(line + 7) * 3)
    const len = Math.min(10 - indent, 2 + Math.floor(noise(line) * 9))
    cv.rect(x + 2 + indent, y + 2 + r, len, 1, ['g', 'c', 'v', 'y'][Math.floor(noise(line + 3) * 4)] ?? 'g')
  }
}

// ---------- idle: drifting, juggling, gardening ----------

function idle(cv: Canvas, t: number) {
  rotate(t, 12, [
    t => {
      spark(cv, 36, 5 + osc(t, 2.6, 1), t, { turned: t % 5 > 4.7 })
      const a = (t / 3) * TAU
      cv.dot(43 + Math.round(Math.cos(a) * 13), 9 + Math.round(Math.sin(a) * 4), tick(t, 4, 2) ? 'y' : 'o')
    },
    t => {
      spark(cv, 36, 6, t, { face: 'happy' })
      for (let i = 0; i < 3; i++) {
        const run = t * 0.8 + i / 3
        const p = run % 1
        const dir = Math.floor(run) % 2 === 0 ? 1 : -1
        const x = 43 + Math.round((p - 0.5) * 16 * dir)
        cv.art(['.x.', 'xxx', '.x.'], x - 1, 3 - Math.round(Math.sin(p * Math.PI) * 3), { x: ['c', 'm', 'g'][i] ?? 'c' })
      }
    },
    t => {
      spark(cv, 28, 6, t)
      cv.art(['.lll..', 'llllll', 'llll..'], 43, 8)
      const grow = Math.min(5, Math.floor((t % 12) / 2))
      for (let i = 0; i < grow; i++) cv.dot(53, 13 - i, 'g')
      if (grow > 1) cv.art(['g.g'], 52, 14 - grow)
      cv.art(['bbbbb', '.bBb.', '.bBb.'], 51, 14)
      for (let i = 0; i < 2; i++) cv.dot(50, 10 + ((tick(t, 6, 4) + i * 2) % 4), 'c')
    },
  ])
}

// ---------- working: terminal, stacking, pondering, delegating; smoke breaks once it's hard ----------

function smokeBreak(cv: Canvas, t: number) {
  monitor(cv, 18, 6, t, false)
  cv.art(['bbbbbbbbb', 'bBBBBBBBb', 'bbbbbbbbb'], 38, 14)
  const x = 35
  const y = 3
  spark(cv, x, y, t, { face: 'sleepy' })
  cv.rect(x + 15, y + 6, 3, 1, 'w')
  cv.dot(x + 18, y + 6, tick(t, 3, 2) ? 'o' : 'r')
  for (let i = 0; i < 4; i++) {
    const p = (t / 2.4 + i / 4) % 1
    const px = x + 19 + Math.round(p * 6 + Math.sin(p * TAU * 1.5))
    const py = y + 5 - Math.round(p * 8)
    cv.rect(px, py, p > 0.6 ? 2 : 1, 1, p < 0.5 ? 'l' : 'L')
  }
  if (t % 3 < 2) cv.art(['.c.', 'ccc'], x + 2, y + 1)
}

function working(cv: Canvas, t: number) {
  if (t >= HARD_SECONDS && Math.floor((t - HARD_SECONDS) / 8) % 4 === 0) return smokeBreak(cv, t)
  rotate(t, 6, [
    t => {
      monitor(cv, 22, 6, t)
      spark(cv, 40, 5 + tick(t, 6, 2), t, { face: 'focus' })
      if (tick(t, 8, 3) === 0) cv.dot(38, 12, 'y')
    },
    t => {
      const p = t % 6
      const placed = Math.min(6, Math.floor(p / 0.9))
      const colors = ['c', 'm', 'g', 'v', 'y', 'o']
      for (let i = 0; i < placed; i++) cv.rect(58, FLOOR - 2 - i * 2, 6, 2, colors[i] ?? 'c')
      const lift = Math.sin(((p % 0.9) / 0.9) * Math.PI)
      const x = 34 + Math.round(lift * 6)
      const y = 6 - Math.round(lift * 2)
      spark(cv, x, y, t, { face: 'happy' })
      cv.rect(x + 5, y - 2, 5, 2, colors[placed % colors.length] ?? 'c')
    },
    t => {
      spark(cv, 36, 6, t, { face: 'wow', turned: tick(t, 7, 2) === 1 })
      cv.art(['.wwwwwww.', 'wwwwwwwww', '.wwwwwww.'], 53, 1)
      cv.dot(51, 5, 'w')
      cv.dot(52, 4, 'w')
      for (let i = 0; i < tick(t, 2, 4); i++) cv.dot(55 + i * 2, 2, 'k')
      const a = t * 4
      cv.dot(43 + Math.round(Math.cos(a) * 9), 11 + Math.round(Math.sin(a) * 3), 'y')
    },
    t => {
      spark(cv, 26, 6, t, { face: 'focus' })
      for (let i = 0; i < 3; i++) {
        const p = (t / 2.4 + i / 3) % 1
        const x = 42 + Math.round(p * 44)
        const y = 9 + osc(t, 0.6, 1, i / 3)
        cv.art(MINI, x, y)
        cv.art(['www', 'wlw'], x + 2, y - 2)
      }
    },
  ])
}

// ---------- loop: the same call again and again, as a coaster loop with no way out ----------

function coaster(cv: Canvas, t: number) {
  const cx = 52
  const cy = 9
  for (let k = 0; k < 40; k++) {
    const a = (k / 40) * TAU
    cv.dot(cx + Math.round(6 * Math.sin(a)), cy + Math.round(6 * Math.cos(a)), 'l')
  }
  cv.rect(26, cy + 6, 56, 1, 'l')
  for (const x of [30, 38, 66, 74]) cv.rect(x, cy + 7, 1, FLOOR - cy - 7, 'L')
  for (let back = 2; back >= 0; back--) {
    const a = ((t - back * 0.08) / 1.4) * TAU
    const x = cx + Math.round(4 * Math.sin(a)) - 3
    const y = cy + Math.round(4 * Math.cos(a)) - 3
    if (back) cv.dot(x + 3, y + 3, back === 1 ? 'o' : 'r')
    else cv.art(MINI, x, y, tick(t, 6, 2) ? { e: 'w' } : {})
  }
  for (let i = 0; i < 3; i++) {
    const a = t * 3 + (i * TAU) / 3
    cv.dot(cx + Math.round(Math.cos(a) * 11), 2 + Math.round(Math.sin(a) * 1), 'y')
  }
}

// ---------- done: fireworks and a hop; a lightbulb if the task was hard ----------

const BURSTS = [
  { at: 0.1, x: 18, y: 4, c: 'm' },
  { at: 1.2, x: 68, y: 3, c: 'c' },
  { at: 2.4, x: 58, y: 2, c: 'y' },
  { at: 3.6, x: 78, y: 5, c: 'g' },
  { at: 4.8, x: 10, y: 3, c: 'v' },
]

function fireworks(cv: Canvas, t: number) {
  for (const b of BURSTS) {
    const dt = t - b.at
    if (dt < 0 || dt > 1.8) continue
    if (dt < 0.5) {
      const y = FLOOR - Math.round(((FLOOR - b.y) * dt) / 0.5)
      cv.dot(b.x, y, 'w')
      cv.dot(b.x, y + 1, 'o')
      continue
    }
    const r = (dt - 0.5) * 9
    for (let k = 0; k < 10; k++) {
      const a = (k / 10) * TAU
      cv.dot(b.x + Math.round(Math.cos(a) * r), b.y + Math.round(Math.sin(a) * r * 0.6), dt > 1.4 ? 'L' : b.c)
    }
  }
}

const BULB = ['.yyy.', 'yHHHy', 'yHHyy', '.yyy.', '.lLl.']

function done(cv: Canvas, t: number, eureka: boolean) {
  fireworks(cv, t)
  const x = 36
  // With the bulb on, the spark stays put so bulb and rays fit above it.
  const y = eureka ? 6 : 6 - Math.round(Math.abs(Math.sin((t * Math.PI) / 0.45)) * 3)
  spark(cv, x, y, t, { face: 'happy', turned: tick(t, 3, 2) === 1 })
  if (!eureka) return
  cv.art(BULB, x + 5, 0)
  if (tick(t, 3, 2)) {
    for (const [dx, dy] of [[3, 1], [11, 1], [4, 0], [10, 0]] as const) cv.dot(x + dx, dy, 'y')
  }
}

// ---------- relax: stargazing, a pool float, cocoa by the window ----------

const SUN = ['.yyy.', 'yyyyy', 'yyyyy', '.yyy.']

function relax(cv: Canvas, t: number) {
  rotate(t, 16, [
    t => {
      for (let x = 18; x <= 62; x++) {
        const h = Math.round(3 - ((x - 40) / 22) ** 2 * 3)
        cv.rect(x, FLOOR - h, 1, h, 'G')
        if (h > 0) cv.dot(x, FLOOR - h, 'g')
      }
      spark(cv, 33, 3, t, { face: 'sleepy' })
      cv.art(['.www', 'ww..', 'ww..', '.www'], 74, 1)
      const p = (t % 5) / 0.8
      if (p < 1) {
        const sx = 82 - Math.round(p * 30)
        const sy = 1 + Math.round(p * 6)
        cv.dot(sx, sy, 'w')
        cv.dot(sx + 1, sy, 'l')
        cv.dot(sx + 2, sy - 1, 'L')
      }
    },
    t => {
      cv.art(SUN, 76, 1)
      spark(cv, 33, 4 + osc(t, 3, 1), t, { face: 'shades' })
      cv.rect(0, 13, W, H - 13, 'C')
      for (let x = 0; x < W; x += 5) cv.rect(x + tick(t, 2, 5), 13, 2, 1, 'c')
      cv.art(['.mwmwmwmwmwmwm.', 'mm...........mm', '.mwmwmwmwmwmwm.'], 33, 13 + osc(t, 3, 1))
    },
    t => {
      cv.rect(56, 2, 18, 11, 'N')
      for (let i = 0; i < 8; i++) {
        cv.dot(57 + Math.floor(noise(i) * 16), 3 + (Math.floor(t * 3 + noise(i + 9) * 10) % 9), 'w')
      }
      cv.rect(56, 2, 18, 1, 'L')
      cv.rect(56, 12, 18, 1, 'L')
      cv.rect(56, 2, 1, 11, 'L')
      cv.rect(73, 2, 1, 11, 'L')
      cv.rect(64, 2, 1, 11, 'L')
      cv.rect(56, 7, 18, 1, 'L')
      spark(cv, 28, 6, t, { face: 'sleepy' })
      cv.art(['wwww.', 'wbbww', 'wwww.', 'wwww.'], 44, 12)
      for (let i = 0; i < 2; i++) {
        const p = (t / 1.6 + i / 2) % 1
        cv.dot(45 + i * 2 + osc(p, 1, 1), 11 - Math.round(p * 5), 'l')
      }
    },
  ])
}

// ---------- error: gone gray under a little storm cloud ----------

function storm(cv: Canvas, t: number) {
  const glitch = t < 0.6
  if (glitch) {
    for (let i = 0; i < 12; i++) {
      const seed = i + tick(t, 20, 100) * 13
      cv.dot(Math.floor(noise(seed) * W), Math.floor(noise(seed + 300) * FLOOR), 'L')
    }
  }
  spark(cv, 36 + (glitch ? tick(t, 20, 3) - 1 : 0), 6, t, { face: 'sad', gray: true })
  cv.art(['..lll...', '.lllll.l', 'llllllll', '.LLLLLL.'], 39, 0)
  if (tick(t, 3, 3) === 0) cv.art(['.y', 'y.', '.y'], 42, 4)
  for (let i = 0; i < 3; i++) cv.dot(40 + i * 3, 4 + ((tick(t, 8, 3) + i) % 3), 'c')
}

// One frame of `mood`, `t` seconds after it began.
export function sceneSvg(mood: Mood, t: number, eureka = false): string {
  const cv = new Canvas()
  stage(cv, t)
  if (mood === 'working') working(cv, t)
  else if (mood === 'loop') coaster(cv, t)
  else if (mood === 'done') done(cv, t, eureka)
  else if (mood === 'relax') relax(cv, t)
  else if (mood === 'error') storm(cv, t)
  else idle(cv, t)
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${SCENE_WIDTH}" height="${SCENE_HEIGHT}" shape-rendering="crispEdges">` +
    `<rect width="${W}" height="${H}" fill="${SKY}"/>${cv}</svg>`
  )
}
