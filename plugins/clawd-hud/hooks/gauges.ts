// The small pixel gauges beside the mascot, as plain SVG strings (no engine imports),
// so the demo renderer can draw exactly what the plugin draws.

export const OK = '#6be38b'
export const LOW = '#ffb547'
export const OUT = '#ff5a5a'
const DIM = '#2c3354'
const RIM = '#a7b0d6'
const HOLE = '#11152a'

// What is left of a window, as a color: plenty, running low, nearly out.
export const charge = (left: number) => (left > 30 ? OK : left > 10 ? LOW : OUT)

const cell = (x: number, y: number, w: number, h: number, c: string) =>
  w > 0 && h > 0 ? `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>` : ''

const pixels = (w: number, h: number, scale: number, body: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w * scale}" height="${h * scale}" shape-rendering="crispEdges">${body}</svg>`

const lit = (left: number) => Math.min(5, Math.max(0, Math.ceil(left / 20)))

export const BATTERY = { width: 48, height: 22 }

// Five cells for what is left of a window. `over` is a spend cap run past 100%:
// an empty shell with a red bolt in it.
export function batterySvg(left: number, over = false): string {
  const n = over ? 0 : lit(left)
  let body = cell(0, 0, 22, 11, RIM) + cell(1, 1, 20, 9, HOLE) + cell(22, 3, 2, 5, RIM)
  for (let i = 0; i < 5; i++) body += cell(2 + i * 4, 2, 3, 7, i < n ? charge(left) : DIM)
  if (over) body += cell(12, 2, 2, 3, OUT) + cell(10, 5, 4, 1, OUT) + cell(10, 6, 2, 3, OUT)
  return pixels(24, 11, 2, body)
}

export const BOLT = { width: 10, height: 14 }

const BOLT_ROWS = ['..xxx', '.xxx.', 'xxxxx', '..xx.', '.xx..', 'xx...', 'x....']

// The prompt cache: a lit bolt while warm, amber in its last minute, gray once cold.
export function boltSvg(color: string): string {
  let body = ''
  BOLT_ROWS.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) if (row[x] === 'x') body += cell(x, y, 1, 1, color)
  })
  return pixels(5, 7, 2, body)
}

export const PILL = { width: 40, height: 6 }

// How full the context window is, as a capsule that fills left to right.
export function pillSvg(percent: number): string {
  const p = Math.min(100, Math.max(0, percent))
  return pixels(40, 6, 1, cell(0, 0, 40, 6, DIM) + cell(1, 1, Math.round((p / 100) * 38), 4, charge(100 - p)))
}

// The same battery for a terminal, which cannot draw SVG.
export const cellsText = (left: number, over = false) => {
  const n = over ? 0 : lit(left)
  return '▰'.repeat(n) + '▱'.repeat(5 - n)
}
