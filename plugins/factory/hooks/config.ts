// The repository's factory settings, in .factory/config.json of the main checkout (never the run's
// worktree, so a branch can't change the rules it is judged by): the review route's model table, the
// paths a run may not change, and the prices its cost is counted in. Every field is optional; a file
// that is missing or wrong leaves the defaults, with a warning. Pure functions, no imports with effects.

import type { Risk, Surface } from '../types'

export type Price = { input: number; output: number; cacheWrite: number; cacheRead: number }
export type FactoryConfig = {
  // The code reviewer's model by risk.
  routing: Record<Risk, string>
  // The reviewers a surface adds, with their models: security is the security reviewer, any other
  // name an extra reviewer (ux, ui-design, or one of the project's own).
  surfaceReviewers: Record<Surface, Record<string, string>>
  // Globs (`*` crosses folders too) of files a run's branch may not modify or delete; adding is fine.
  protectedPaths: string[]
  // USD per million tokens, by model id or family (opus, sonnet, haiku, fable).
  prices: Record<string, Price>
  warnings: string[]
}

// The defaults: the table from the factory's design. The builder always runs on opus; a diff that
// calls for depth still moves the code reviewer to opus and adds the security reviewer (reviewPlan).
export const DEFAULT_CONFIG: FactoryConfig = {
  routing: { low: 'haiku', medium: 'sonnet', high: 'sonnet' },
  surfaceReviewers: { ui: { ux: 'sonnet', 'ui-design': 'haiku' }, security: { security: 'opus' } },
  protectedPaths: [],
  // Published API list prices, per million tokens; cache writes at the 5-minute rate.
  prices: {
    fable: { input: 10, output: 50, cacheWrite: 12.5, cacheRead: 0.25 },
    opus: { input: 4, output: 20, cacheWrite: 5, cacheRead: 0.2 },
    sonnet: { input: 2, output: 10, cacheWrite: 2.5, cacheRead: 0.2 },
    haiku: { input: 0.1, output: 0.5, cacheWrite: 0.125, cacheRead: 0.01 },
  },
  warnings: [],
}

const MODEL = /^[a-z0-9][a-z0-9.\-[\]]{0,60}$/i
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)

export function parseConfig(text: string | null): FactoryConfig {
  const out: FactoryConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG)) as FactoryConfig
  if (text === null) return out
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (e) {
    return { ...out, warnings: [`.factory/config.json is not valid JSON (${String(e).slice(0, 80)}): the defaults apply`] }
  }
  if (!isObj(raw)) return { ...out, warnings: ['.factory/config.json is not an object: the defaults apply'] }
  const warn = (w: string) => out.warnings.push(`.factory/config.json: ${w}`)
  if (isObj(raw.routing)) {
    for (const risk of ['low', 'medium', 'high'] as Risk[]) {
      const v = raw.routing[risk]
      // { "code": "haiku" } as in the design, or the model alone.
      const model = isObj(v) ? v.code : v
      if (model === undefined) continue
      if (typeof model === 'string' && MODEL.test(model)) out.routing[risk] = model
      else warn(`routing.${risk} names no model`)
    }
  }
  const surfaces = raw.surface_reviewers ?? raw.surfaceReviewers
  if (isObj(surfaces)) {
    for (const s of ['ui', 'security'] as Surface[]) {
      const v = surfaces[s]
      if (v === undefined) continue
      if (!isObj(v)) {
        warn(`surface_reviewers.${s} is not a map of reviewer to model`)
        continue
      }
      const map: Record<string, string> = {}
      for (const [k, m] of Object.entries(v)) {
        // The design calls the visual reviewer ui: here it is ui-design.
        const name = (k === 'ui' ? 'ui-design' : k).toLowerCase().replace(/[^a-z0-9-]+/g, '-').slice(0, 24)
        if (name === 'code') warn(`surface_reviewers.${s}.code ignored: the code reviewer always runs, by risk`)
        else if (typeof m === 'string' && MODEL.test(m) && name) map[name] = m
        else warn(`surface_reviewers.${s}.${k} names no model`)
      }
      out.surfaceReviewers[s] = map
    }
  }
  const paths = raw.protected_paths ?? raw.protectedPaths
  if (paths !== undefined) {
    if (Array.isArray(paths) && paths.every(p => typeof p === 'string' && p.trim())) out.protectedPaths = (paths as string[]).map(p => p.trim().replace(/^\.\//, ''))
    else warn('protected_paths is not a list of globs')
  }
  const prices = raw.prices_usd_per_mtok ?? raw.prices
  if (isObj(prices)) {
    for (const [model, p] of Object.entries(prices)) {
      if (!isObj(p) || typeof p.input !== 'number' || typeof p.output !== 'number') {
        warn(`prices for ${model} need numbers for input and output`)
        continue
      }
      const num = (v: unknown, d: number) => (typeof v === 'number' && v >= 0 ? v : d)
      out.prices[model] = { input: p.input, output: p.output, cacheWrite: num(p.cache_write_5m ?? p.cacheWrite, p.input * 1.25), cacheRead: num(p.cache_read ?? p.cacheRead, p.input * 0.1) }
    }
  }
  return out
}

// ---------- protected paths ----------

// fnmatch-like: `*` and `?` cross folders too, so `.github/*` covers every workflow.
export function globMatch(path: string, pattern: string): boolean {
  const re = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*+/g, '.*').replace(/\?/g, '.')
  return new RegExp(`^${re}$`).test(path)
}

// The branch's changes (git diff --name-status -z) to protected files: a modified, deleted or renamed
// one counts (a rename by its old path); a new file doesn't.
export function protectedHits(nameStatusZ: string, patterns: readonly string[]): string[] {
  if (!patterns.length) return []
  const f = nameStatusZ.split('\0')
  const hits: string[] = []
  for (let i = 0; i < f.length; i++) {
    const status = f[i]!
    if (!status) continue
    const old = f[i + 1] ?? ''
    i += /^[RC]/.test(status) ? 2 : 1
    if (status.startsWith('A') || !old) continue
    if (patterns.some(p => globMatch(old, p))) hits.push(`${status[0]} ${old}`)
  }
  return hits
}

// ---------- cost ----------

export type Usage = { input: number; output: number; cacheWrite: number; cacheRead: number }
export const addUsage = (a: Usage | undefined, u: { input_tokens?: number; output_tokens?: number; cache_creation_input_tokens?: number; cache_read_input_tokens?: number }): Usage => ({
  input: (a?.input ?? 0) + (u.input_tokens ?? 0),
  output: (a?.output ?? 0) + (u.output_tokens ?? 0),
  cacheWrite: (a?.cacheWrite ?? 0) + (u.cache_creation_input_tokens ?? 0),
  cacheRead: (a?.cacheRead ?? 0) + (u.cache_read_input_tokens ?? 0),
})

// A model's price: its exact id, else its family's (claude-opus-5-5 → opus). None: null.
export function priceOf(model: string, prices: Record<string, Price>): Price | null {
  if (prices[model]) return prices[model]!
  const family = /(fable|opus|sonnet|haiku)/i.exec(model)?.[1]?.toLowerCase()
  return family && prices[family] ? prices[family]! : null
}

// The API-equivalent cost of a run's agents, by model: on a subscription it is relative spend, not
// the bill. A model with no price is counted as unpriced, not as free.
export function costOf(usage: Record<string, Usage>, prices: Record<string, Price>): { usd: number; byModel: { model: string; usd: number | null }[] } {
  const byModel = Object.entries(usage).map(([model, u]) => {
    const p = priceOf(model, prices)
    return { model, usd: p ? (u.input * p.input + u.output * p.output + u.cacheWrite * p.cacheWrite + u.cacheRead * p.cacheRead) / 1e6 : null }
  })
  return { usd: byModel.reduce((n, m) => n + (m.usd ?? 0), 0), byModel }
}

export const usd = (n: number) => (n >= 10 ? `$${n.toFixed(0)}` : n >= 0.01 ? `$${n.toFixed(2)}` : n > 0 ? '<$0.01' : '$0')

export function costLine(usage: Record<string, Usage> | undefined, prices: Record<string, Price>): string {
  if (!usage || !Object.keys(usage).length) return 'Cost: nothing counted yet.'
  const c = costOf(usage, prices)
  const unpriced = c.byModel.filter(m => m.usd === null).map(m => m.model)
  const priced = c.byModel.filter(m => m.usd !== null).map(m => `${m.model} ${usd(m.usd!)}`)
  const parts = [...(priced.length ? [priced.join(', ')] : []), ...(unpriced.length ? [`no price for ${unpriced.join(', ')}`] : [])]
  return `Cost: ${usd(c.usd)} API-equivalent (${parts.join('; ')}).`
}
