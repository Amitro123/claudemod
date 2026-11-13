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
// --no-show-signature: a person's log.showSignature would print signature text into the output.
// Each commit starts with an empty field (%x00), a path is never empty: the next field is its id.
export const historyArgs = (base: string) =>
  ['log', '--no-show-signature', '--no-renames', '--diff-merges=first-parent', '--diff-filter=A', '--name-only', '-z', '--format=%x00%H', `${base}..HEAD`]

// The new files in the index, before the factory's own commit: a file the builder staged itself never
// went through the untracked-file filter. --no-renames for the same reason as the history scan: a
// staged `git mv config.txt .env` is a rename to git's default diff, and --diff-filter=A misses it.
export const stagedAddsArgs = ['diff', '--cached', '--no-renames', '--name-only', '--diff-filter=A', '-z']

const COMMIT_ID =/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/
const malformed = (why: string) => new Error(`the history scan's output is not the shape it asked git for: ${why}`)

// The never-commit files in historyArgs' output, as leftOut shows them, each with the commits that
// added it (newest first). Output in any other shape throws: what git printed besides the paths
// (a signature, a warning) would otherwise read as paths, or hide them.
export function historyLeaks(logZ: string): { path: string; commits: string[] }[] {
  const found = new Map<string, string[]>()
  if (logZ === '') return []
  const fields = logZ.split('\0')
  if (fields[0] !== '' || fields[fields.length - 1] !== '') throw malformed('it does not start and end with a NUL')
  // Per commit: '', its id, then its paths, the first after the newline git puts there; the last
  // field is the empty one after the closing NUL.
  let i = 0
  while (i < fields.length - 1) {
    if (fields[i] !== '') throw malformed(`a field where a commit should start (field ${i})`)
    const commit = fields[i + 1] ?? ''
    if (!COMMIT_ID.test(commit)) throw malformed(`not a commit id (field ${i + 1})`)
    i += 2
    for (let first = true; i < fields.length - 1 && fields[i] !== ''; i++, first = false) {
      const field = fields[i]!
      if (field.startsWith('\n') !== first) throw malformed(`a path out of place (field ${i})`)
      const path = first ? field.slice(1) : field
      if (!path) throw malformed(`an empty path (field ${i})`)
      if (!neverCommit(path)) continue
      const [shown] = leftOut([path])
      const commits = found.get(shown!) ?? []
      if (!commits.includes(commit)) commits.push(commit)
      found.set(shown!, commits)
    }
  }
  return [...found].map(([path, commits]) => ({ path, commits }))
}
