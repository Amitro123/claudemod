// GENERATED from shared/runtime.ts by tools/sync-texts.mjs: edit that file, not this one.
// Helpers more than one mod runs against the engine: the project a saved list or goal belongs to,
// whether another mod's command is there, and the three-way merge two sessions' saves go through.
// Edit it here, then run `node tools/sync-texts.mjs`: a mod can import nothing outside its own folder,
// so each one that uses it keeps a copy in hooks/runtime.ts.

import type { EngineInterface } from 'claude-code'

import { projectFrom } from './texts'

// The project a session's saved state belongs to: the main repository, the same for each of its git
// worktrees (a session in a worktree has a root of its own), else the session's root. Asked of git once
// per root.
const projects = new Map<string, string>()
export async function projectOf($: EngineInterface): Promise<string> {
  const root = await $.session.root()
  const known = projects.get(root)
  if (known) return known
  const out = await $.process.run(['git', 'rev-parse', '--git-common-dir'], { cwd: root, timeoutMs: 5_000 }).catch(() => null)
  const project = projectFrom(root, out && out.exitCode === 0 ? out.stdout : '')
  projects.set(root, project)
  return project
}

// Whether a command (another mod's, so that mod is installed) is registered now. Mods start in no set
// order, so a mod asks again until it is there; it remembers the answer in an atom of its own (the
// engine reads state only from an atom the module itself declares, so that part can't be shared).
export async function hasCommand($: EngineInterface, name: string): Promise<boolean> {
  return (await $.command.list().catch(() => [])).some(c => c.name === name)
}

// ---------- merging two sessions' saves ----------

const same = (x: unknown, y: unknown) => JSON.stringify(x) === JSON.stringify(y)

// One value of a three-way merge: what changed here since `base` wins, else what the other session has.
export const pick = <T,>(mine: T, base: T, theirs: T): T => (same(mine, base) ? theirs : mine)

// A list by id, merged three ways with what another session saved meanwhile. `base` is the list as this
// session last loaded or saved it: an item changed here wins, one changed only there is taken, and an
// item either side deleted stays deleted.
export function mergeLists<T extends { id: string }>(base: T[], mine: T[], stored: T[]): T[] {
  const was = new Map(base.map(i => [i.id, i]))
  const there = new Map(stored.map(i => [i.id, i]))
  const held = new Set(mine.map(i => i.id))
  const kept = mine.flatMap(i => {
    const before = was.get(i.id)
    if (!before || !same(before, i)) return [i]
    const other = there.get(i.id)
    return other ? [pick(i, before, other)] : []
  })
  return [...kept, ...stored.filter(i => !held.has(i.id) && !was.has(i.id))]
}
