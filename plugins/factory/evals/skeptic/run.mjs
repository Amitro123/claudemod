// The skeptic, on real findings from this repository's reviews: known false positives it should set
// aside, and real bugs it must keep. Each case runs the skeptic's own prompt (read from hooks/flow.ts)
// on a snapshot of the repository from before the fix. Needs claude on PATH and a model to call.
// Usage (from the repository root): node plugins/factory/evals/skeptic/run.mjs [runs] [case ids...]
import { execFileSync, spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const here = new URL('.', import.meta.url).pathname
const root = execFileSync('git', ['-C', here, 'rev-parse', '--show-toplevel']).toString().trim()
const [runsArg = '2', ...only] = process.argv.slice(2)
const cases = JSON.parse(readFileSync(join(here, 'cases.json'), 'utf8')).filter(c => !only.length || only.includes(c.id))
// The role and the prompt as the factory sends them, from flow.ts itself, so the eval can't drift.
const flow = readFileSync(join(root, 'plugins/factory/hooks/flow.ts'), 'utf8')
const role = /\n  skeptic: `(.*?)`,\n/s.exec(flow)[1]
const body = /export function skepticPrompt[\s\S]*?\n  \]\.join/.exec(flow)[0]
const lines = [...body.matchAll(/^\s*(?:'([^']*)'|"([^"]*)"),?$/gm)].map(m => m[1] ?? m[2])
const intro = /'(The reviewers raised[^']*)'/.exec(body)[1]
const out = mkdtempSync(join(tmpdir(), 'skeptic-eval-'))
const snapshot = c => {
  const wt = join(out, `wt-${c.id}`)
  if (!existsSync(wt)) {
    execFileSync('git', ['-C', root, 'worktree', 'add', '-q', '--detach', wt, c.repo])
    if (c.patch) execFileSync('git', ['-C', wt, 'apply', join(here, c.patch)])
  }
  return wt
}
const one = (c, n) => new Promise(resolve => {
  const wt = snapshot(c)
  const prompt = [
    `A change for: ${c.feature}`,
    `There is no spec. The change is the checkout ${wt} against ${c.repo}, uncommitted work included.`,
    `The change is in the person's checkout ${wt}: read it there by absolute paths, with the Read, Grep and Glob tools rather than shell commands, and change nothing.`,
    intro,
    `F1. ${c.finding}`,
    ...lines.filter(l => /^End your answer|^F<n>: /.test(l)),
  ].join('\n')
  const child = spawn('claude', ['-p', prompt, '--model', 'sonnet', '--append-system-prompt', role, '--allowedTools', 'Read,Grep,Glob,Bash(git log*),Bash(git show*),Bash(ls *)', '--output-format', 'json'], { cwd: wt, stdio: ['ignore', 'pipe', 'pipe'] })
  let raw = ''
  child.stdout.on('data', d => (raw += d))
  child.on('exit', () => {
    let answer = ''
    try { answer = JSON.parse(raw).result ?? '' } catch { answer = raw }
    const m = [...answer.matchAll(/^[ \t>*_-]*F1[ \t]*[:.)-][ \t]*\**[ \t]*(STANDS|REFUTED|DOWNGRADED|UNVERIFIED|DESIGN)\b[ \t:—–-]*(.*)$/gim)].at(-1)
    const r = { id: c.id, truth: c.truth, run: n, ruling: m ? m[1].toUpperCase() : 'NONE', why: m ? m[2].slice(0, 300) : '' }
    appendFileSync(join(out, 'results.jsonl'), JSON.stringify(r) + '\n')
    writeFileSync(join(out, `answer-${c.id}-${n}.md`), answer)
    resolve(r)
  })
})
for (const c of cases) snapshot(c)
const queue = cases.flatMap(c => Array.from({ length: Number(runsArg) }, (_, i) => () => one(c, i + 1)))
const results = []
await Promise.all(Array.from({ length: 6 }, async () => { while (queue.length) results.push(await queue.shift()()) }))
for (const r of results.sort((a, b) => a.id.localeCompare(b.id) || a.run - b.run)) console.log(`${r.truth.padEnd(14)} ${r.id.padEnd(22)} ${r.run} ${r.ruling}`)
const fp = results.filter(r => r.truth === 'false-positive'), tp = results.filter(r => r.truth === 'real')
console.log(`\nfalse positives set aside (refuted, design or unverified): ${fp.filter(r => ['REFUTED', 'DESIGN', 'UNVERIFIED'].includes(r.ruling)).length}/${fp.length}`)
console.log(`real findings kept (stands, or downgraded and kept as minor): ${tp.filter(r => ['STANDS', 'DOWNGRADED'].includes(r.ruling)).length}/${tp.length}`)
console.log(`answers and worktrees: ${out} (remove the worktrees with git worktree prune after deleting it)`)
