// No imports, so the real-git tests (tests/history.real-git.test.mjs) load it in plain Node.

// What never goes into a commit, even where the project's .gitignore misses it: installed dependencies
// and credentials. Narrow on purpose: a match the builder committed stops the run. Build output
// (dist/, build/) isn't on it: a folder of that name can be source (cmd/build/), and one that is
// output is the .gitignore's to keep out. A sample .env (.env.example) and a key or certificate among
// test fixtures are files a change may well add.
const DEPENDENCIES = /(^|\/)(node_modules|\.venv|venv|__pycache__)(\/|$)/
const ENV_FILE = /(^|\/)\.env(\.[^/]*)?$/
const SAMPLE_ENV = /(^|\/)\.env\.(example|sample|template|dist)$/i
const KEY_FILE = /\.(pem|key|p12|pfx)$/i
const TEST_DIR = /(^|\/)(tests?|__tests__|spec|fixtures|__fixtures__|testdata)\//i
export const neverCommit = (path: string) =>
  DEPENDENCIES.test(path) || (ENV_FILE.test(path) && !SAMPLE_ENV.test(path)) || (KEY_FILE.test(path) && !TEST_DIR.test(path))

// The files left out, as a person reads them: a file inside an excluded folder (node_modules/)
// as that folder, once, so a whole install doesn't list file by file.
export function leftOut(paths: readonly string[]): string[] {
  const out: string[] = []
  for (const p of paths) {
    const parts = p.split('/')
    let shown = p
    for (let i = 1; i < parts.length; i++) {
      const dir = `${parts.slice(0, i).join('/')}/`
      if (neverCommit(dir)) {
        shown = dir
        break
      }
    }
    if (!out.includes(shown)) out.push(shown)
  }
  return out
}

// Every file a commit since the base added, commit by commit: what is pushed is the history, not the
// net diff, so a .env added and deleted again, or renamed away, is still in it. By name only, never
// contents. --no-renames: a rename is a delete and an add, with no similarity guess deciding it. A
// merge is compared with its first parent, so a file the merge itself adds counts (git log shows a
// merge with no files otherwise); the merged branch's own commits are walked as well.
// Each commit starts with an empty field (%x00), a path is never empty: the next field is its id.
export const historyArgs = (base: string) =>
  ['log', '--no-renames', '--diff-merges=first-parent', '--diff-filter=A', '--name-only', '-z', '--format=%x00%H', `${base}..HEAD`]

// The never-commit files in historyArgs' output, as leftOut shows them, each with the commits that
// added it (newest first).
export function historyLeaks(logZ: string): { path: string; commits: string[] }[] {
  const found = new Map<string, string[]>()
  const fields = logZ.split('\0')
  let commit = ''
  let first = false
  for (let i = 0; i < fields.length; i++) {
    if (fields[i] === '') {
      commit = fields[++i] ?? ''
      first = true
      continue
    }
    // git puts a newline between a commit's format line and its first path.
    const path = first ? fields[i]!.replace(/^\n/, '') : fields[i]!
    first = false
    if (!path || !neverCommit(path)) continue
    const [shown] = leftOut([path])
    const commits = found.get(shown!) ?? []
    if (!commits.includes(commit)) commits.push(commit)
    found.set(shown!, commits)
  }
  return [...found].map(([path, commits]) => ({ path, commits }))
}
