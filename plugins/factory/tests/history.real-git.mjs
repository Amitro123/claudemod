// The branch-history scan for files the factory never commits, against real git in disposable
// repositories. `claude plugin test` can't start a process, so this runs in plain Node:
//   node --experimental-strip-types --test plugins/factory/tests/history.real-git.mjs
// Node 22.12+ (type stripping behind the flag, ES module detection on by default), git 2.34+
// (--diff-merges; SSH commit signing) and ssh-keygen on PATH (the signed-commit test makes a
// throwaway key; it fails, never skips, without one). CI runs it as the factory-history job in
// .github/workflows/mods.yml.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { historyArgs, historyLeaks, neverCommit, stagedAddsArgs } from '../hooks/history.ts'

// Kept from the machine's git config and hooks. File contents are placeholders: the scan reads
// names, never contents.
// `inBase`: files the base commit already has. `signed`: every commit is signed with a throwaway
// SSH key and the repository shows signatures in git log (its own config only, as a person's
// log.showSignature would).
function repo(t, inBase = [], { signed = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'factory-history-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  const work = join(dir, 'work')
  mkdirSync(work)
  writeFileSync(join(dir, 'gitconfig'), '')
  const env = { ...process.env, GIT_CONFIG_GLOBAL: join(dir, 'gitconfig'), GIT_CONFIG_NOSYSTEM: '1' }
  const run = (...args) => {
    const out = spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...(signed ? [] : ['-c', 'commit.gpgsign=false']), '-c', `core.hooksPath=${join(dir, 'no-hooks')}`, ...args], { cwd: work, env, encoding: 'utf8' })
    return { exitCode: out.status ?? 1, stdout: out.stdout ?? '', stderr: out.stderr ?? '' }
  }
  const git = (...args) => {
    const out = run(...args)
    if (out.exitCode !== 0) throw new Error(`git ${args.join(' ')}: ${out.stderr}`)
    return out.stdout
  }
  const write = path => {
    mkdirSync(dirname(join(work, path)), { recursive: true })
    writeFileSync(join(work, path), 'PLACEHOLDER=not-a-secret\n')
  }
  const commit = message => {
    git('add', '-A')
    git('commit', '-q', '-m', message)
    return git('rev-parse', 'HEAD').trim()
  }
  git('init', '-q', '-b', 'main')
  if (signed) {
    const key = join(dir, 'signing-key')
    const made = spawnSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', '', '-C', 'factory-test', '-f', key], { encoding: 'utf8' })
    if (made.error || made.status !== 0) throw new Error(`ssh-keygen is needed for the signed-commit test: ${made.error ?? made.stderr}`)
    for (const [k, v] of [['gpg.format', 'ssh'], ['user.signingkey', `${key}.pub`], ['commit.gpgsign', 'true'], ['log.showSignature', 'true']]) git('config', '--local', k, v)
  }
  for (const path of ['README.md', ...inBase]) write(path)
  const base = commit('base')
  const scan = () => {
    const out = run(...historyArgs(base))
    if (out.exitCode !== 0) throw new Error(`scan failed: ${out.stderr}`)
    return historyLeaks(out.stdout)
  }
  return { base, git, run, write, commit, scan }
}

// The check before the factory's own commit: new files in the index that the builder staged itself.
test('a file the builder staged as a rename to .env (git mv) is a new file to the staged check, not a rename', t => {
  const r = repo(t, ['config.txt', 'notes.md'])
  r.git('mv', 'config.txt', '.env')
  r.git('mv', 'notes.md', 'docs.md')
  const staged = r.git(...stagedAddsArgs).split('\0').filter(Boolean)
  assert.deepEqual(staged.sort(), ['.env', 'docs.md'])
  assert.deepEqual(staged.filter(neverCommit), ['.env'])
  // Without --no-renames, git's rename detection calls both renames and --diff-filter=A sees neither.
  const withoutFlag = stagedAddsArgs.filter(a => a !== '--no-renames')
  assert.equal(r.git(...withoutFlag), '')
})

test('a .env added and then deleted: the net diff is empty, the history still has it', t => {
  const r = repo(t)
  r.write('.env')
  const added = r.commit('add env')
  r.git('rm', '-q', '.env')
  r.commit('drop env')
  assert.equal(r.git('diff', '--name-only', r.base, 'HEAD'), '')
  assert.deepEqual(r.scan(), [{ path: '.env', commits: [added] }])
})

test("an ordinary file of the base renamed to .env (git's own rename detection calls it a rename, not an add)", t => {
  const r = repo(t, ['app/settings.txt'])
  r.git('mv', 'app/settings.txt', 'app/.env')
  const renamed = r.commit('rename')
  assert.equal(r.git('diff', '--name-status', r.base, 'HEAD').trim().split(/\s+/)[0].startsWith('R'), true)
  assert.deepEqual(r.scan(), [{ path: 'app/.env', commits: [renamed] }])
})

test('a key renamed to an ordinary name later in the range', t => {
  const r = repo(t)
  r.write('certs/server.key')
  const added = r.commit('key')
  r.git('mv', 'certs/server.key', 'certs/server.txt')
  r.commit('rename away')
  assert.equal(r.git('diff', '--name-only', r.base, 'HEAD').trim(), 'certs/server.txt')
  assert.deepEqual(r.scan(), [{ path: 'certs/server.key', commits: [added] }])
})

test('a clean history passes: ordinary files, renames, deletes, a sample .env, a fixture key', t => {
  const r = repo(t)
  r.write('src/a.ts')
  r.write('.env.example')
  r.write('tests/fixtures/server.pem')
  r.commit('work')
  r.git('mv', 'src/a.ts', 'src/b.ts')
  r.commit('rename')
  r.git('rm', '-q', 'src/b.ts')
  r.commit('drop')
  assert.deepEqual(r.scan(), [])
})

test('a key the merge commit itself adds, deleted later (git log shows a merge with no files by default)', t => {
  const r = repo(t)
  r.git('checkout', '-q', '-b', 'side')
  r.write('side.txt')
  r.commit('side')
  r.git('checkout', '-q', 'main')
  r.write('main.txt')
  r.commit('main')
  r.git('merge', '-q', '--no-ff', '--no-commit', 'side')
  r.write('deploy.pem')
  const merge = r.commit('merge side')
  r.git('rm', '-q', 'deploy.pem')
  r.commit('drop key')
  assert.deepEqual(r.scan(), [{ path: 'deploy.pem', commits: [merge] }])
})

test("a .env a merged branch added and deleted is found in that branch's own commit", t => {
  const r = repo(t)
  r.git('checkout', '-q', '-b', 'side')
  r.write('.env.local')
  const added = r.commit('env')
  r.git('rm', '-q', '.env.local')
  r.commit('drop env')
  r.git('checkout', '-q', 'main')
  r.write('main.txt')
  r.commit('main')
  r.git('merge', '-q', '--no-ff', '-m', 'merge side', 'side')
  assert.deepEqual(r.scan(), [{ path: '.env.local', commits: [added] }])
})

test('names stay as they are (NUL-separated): spaces and non-ASCII', t => {
  const r = repo(t)
  r.write('my app/שלום/.env.production')
  r.write('my app/ok.txt')
  const added = r.commit('env')
  assert.deepEqual(r.scan(), [{ path: 'my app/שלום/.env.production', commits: [added] }])
})

test('installed dependencies committed twice show as their folder, once, with both commits', t => {
  const r = repo(t)
  r.write('node_modules/x/a.js')
  r.write('node_modules/x/b.js')
  const first = r.commit('deps')
  r.git('rm', '-rq', 'node_modules')
  r.commit('drop deps')
  r.write('node_modules/y/c.js')
  const second = r.commit('deps again')
  assert.deepEqual(r.scan(), [{ path: 'node_modules/', commits: [second, first] }])
})

test('a base git cannot resolve fails the scan instead of reading as clean', t => {
  const r = repo(t)
  const out = r.run(...historyArgs('0123456789abcdef0123456789abcdef01234567'))
  assert.notEqual(out.exitCode, 0)
})

test('signed commits with log.showSignature on: the signature text stays out of the scan', t => {
  const r = repo(t, [], { signed: true })
  r.write('src/ok.ts')
  r.commit('ok')
  r.write('.env')
  const added = r.commit('env')
  // The repository does print signatures in git log, so the scan is tested where it matters.
  const shown = r.run('log', '--format=%x00%H', '-z', `${r.base}..HEAD`)
  assert.equal(shown.exitCode, 0)
  assert.notEqual(shown.stdout.split('\0')[0], '')
  assert.deepEqual(r.scan(), [{ path: '.env', commits: [added] }])
})

test('a range with no commits is a clean scan', t => {
  const r = repo(t)
  assert.deepEqual(r.scan(), [])
})

const A = 'a'.repeat(40)
const B = 'b'.repeat(64)

test('output git did not frame as the scan asks for is refused, never read as clean', () => {
  for (const [why, out] of [
    ['text before the first commit (a signature line)', `No signature\n\0${A}\0\n.env\0`],
    ['text between commits (a signature line)', `\0${A}\0\nok.txt\0No signature\n\0${B}\0\n.env\0`],
    ['a commit id that is not 40 or 64 hex digits', `\0${'a'.repeat(39)}\0\n.env\0`],
    ['a commit id in capitals', `\0${A.toUpperCase()}\0\n.env\0`],
    ['a first path without the newline git puts before it', `\0${A}\0.env\0`],
    ['output cut short (no closing NUL)', `\0${A}\0\n.env`],
    ['a commit id with nothing after it', `\0${A}`],
    ['plain text', 'fatal: something'],
  ]) assert.throws(() => historyLeaks(out), /not the shape/, why)
})

test('framed output parses: no commits, a commit with no added file, NUL-separated names as they are', () => {
  assert.deepEqual(historyLeaks(''), [])
  assert.deepEqual(historyLeaks(`\0${A}\0`), [])
  assert.deepEqual(historyLeaks(`\0${A}\0\nsrc/a.ts\0src/b.ts\0\0${B}\0`), [])
  assert.deepEqual(historyLeaks(`\0${A}\0\n my app/ .env \0my app/.env\0`), [{ path: 'my app/.env', commits: [A] }])
  assert.deepEqual(historyLeaks(`\0${B}\0\nok.txt\0\0${A}\0\ncerts/server.key\0`), [{ path: 'certs/server.key', commits: [A] }])
})
