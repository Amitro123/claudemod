// The branch-history scan for files the factory never commits, against real git in disposable
// repositories. `claude plugin test` can't start a process, so this runs in plain Node:
//   node --experimental-strip-types --test plugins/factory/tests/history.real-git.mjs
// Node 22.12+ (type stripping behind the flag, ES module detection on by default) and git 2.31+
// (--diff-merges). CI runs it as the factory-history job in .github/workflows/mods.yml.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { historyArgs, historyLeaks } from '../hooks/history.ts'

// Kept from the machine's git config and hooks. File contents are placeholders: the scan reads
// names, never contents.
// `inBase`: files the base commit already has.
function repo(t, inBase = []) {
  const dir = mkdtempSync(join(tmpdir(), 'factory-history-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  const work = join(dir, 'work')
  mkdirSync(work)
  writeFileSync(join(dir, 'gitconfig'), '')
  const env = { ...process.env, GIT_CONFIG_GLOBAL: join(dir, 'gitconfig'), GIT_CONFIG_NOSYSTEM: '1' }
  const run = (...args) => {
    const out = spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', '-c', `core.hooksPath=${join(dir, 'no-hooks')}`, ...args], { cwd: work, env, encoding: 'utf8' })
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
  for (const path of ['README.md', ...inBase]) write(path)
  const base = commit('base')
  const scan = () => {
    const out = run(...historyArgs(base))
    if (out.exitCode !== 0) throw new Error(`scan failed: ${out.stderr}`)
    return historyLeaks(out.stdout)
  }
  return { base, git, run, write, commit, scan }
}

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
