// Copies each shared/ file into the mods that use it (a mod can import nothing outside its folder):
// texts.ts, the wording one mod writes and another reads, and runtime.ts, helpers they run against the
// engine. `--check` only reports a copy that differs, and exits 1.
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const SHARED = [
  { file: 'texts.ts', mods: ['followups', 'goal-run', 'brain-hud', 'factory'] },
  { file: 'runtime.ts', mods: ['followups', 'goal-run', 'brain-hud', 'factory'] },
]
const check = process.argv.includes('--check')
let stale = 0
for (const { file, mods } of SHARED) {
  const source = readFileSync(join(root, 'shared', file), 'utf8')
  const copy = `// GENERATED from shared/${file} by tools/sync-texts.mjs: edit that file, not this one.\n${source}`
  for (const mod of mods) {
    const target = join(root, 'plugins', mod, 'hooks', file)
    const now = existsSync(target) ? readFileSync(target, 'utf8') : ''
    if (now === copy) continue
    if (check) {
      console.error(`stale: plugins/${mod}/hooks/${file} (run node tools/sync-texts.mjs)`)
      stale++
    } else {
      writeFileSync(target, copy)
      console.log(`wrote plugins/${mod}/hooks/${file}`)
    }
  }
}
process.exit(stale ? 1 : 0)
