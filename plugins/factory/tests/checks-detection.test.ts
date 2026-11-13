// chk-01: deterministic (no model, no cost) cases for hooks/checks.ts of the pinned plugin copy.
// Run: claude plugin test plugins/factory (part of the default run).
import { describe, expect, test } from 'claude-code/testing'

import { allowedCommand, detectProjectChecks, MAX_DIRS, NOTHING_RAN } from '../hooks/checks'
import type { ChecksIO } from '../hooks/checks'
import { argvs, pkg, repo } from './support/checks-repo'

const run = (files: Record<string, string>, opts = {}) => detectProjectChecks(repo(files), '/r', opts)

describe('chk-01 detection (S1-S6, D1)', () => {
  test("a Claude Code plugin's tests: the root when it is one, and each plugin the change touched in a marketplace", async () => {
    expect(argvs(await run({ '.claude-plugin/plugin.json': '{}', 'hooks/register.tsx': '' }))).toEqual(['claude plugin test .'])
    const market = { '.claude-plugin/marketplace.json': '{}', 'plugins/a/.claude-plugin/plugin.json': '{}', 'plugins/a/hooks/x.ts': '', 'plugins/b/.claude-plugin/plugin.json': '{}', 'plugins/b/hooks/y.ts': '' }
    expect(argvs(await run(market, { touched: ['plugins/a/hooks/x.ts'] }))).toEqual(['claude plugin test plugins/a'])
    expect(argvs(await run(market))).toEqual([])
  })

  test("a change only to a plugin's .claude-plugin/plugin.json, or a hidden folder deep in a project, still touches the folders above it", async () => {
    const market = { '.claude-plugin/marketplace.json': '{}', 'plugins/a/.claude-plugin/plugin.json': '{}', 'plugins/a/hooks/x.ts': '' }
    expect(argvs(await run(market, { touched: ['plugins/a/.claude-plugin/plugin.json'] }))).toEqual(['claude plugin test plugins/a'])
    // Deeper than the scan (depth 4): found only as a touched folder, and a file in its .cfg/ touches it.
    const deep = { 'a/b/c/d/go.mod': '', 'a/b/c/d/.cfg/x.json': '' }
    expect(argvs(await run(deep, { touched: ['a/b/c/d/.cfg/x.json'] }))).toEqual(['go -C a/b/c/d test ./...'])
    // An ignored folder still stops the walk there: nothing under node_modules/ counts as touched.
    expect(argvs(await run({ 'node_modules/p/package.json': '{}', 'node_modules/p/go.mod': '' }, { touched: ['node_modules/p/go.mod'] }))).toEqual([])
  })

  test('root node project: test and lint found', async () => {
    const r = await run({ 'package.json': pkg({ test: 'vitest', lint: 'eslint .' }) })
    expect(argvs(r)).toEqual(['npm test', 'npm run lint'])
  })

  test('D1: python tests one level down are found, not only root config files', async () => {
    const r = await run({ 'svc/tests/test_a.py': '', 'svc/pyproject.toml': '[tool.pytest.ini_options]' })
    expect(argvs(r).some(c => c.includes('pytest'))).toBe(true)
  })

  test('python tests up to depth 3 are found by their top directory', async () => {
    const r = await run({ 'tools/x/tests/test_deep.py': '' })
    expect(argvs(r)).toContain('python -m pytest -q tools')
  })

  test('S3 workaround: a nested JS package is found when the change touched it (and it is installed)', async () => {
    const files = { 'packages/a/package.json': pkg({ test: 'jest' }), 'packages/a/node_modules/x/index.js': '', 'packages/a/src/i.ts': '' }
    const r = await run(files, { touched: ['packages/a/src/i.ts'] })
    expect(argvs(r)).toContain('npm --prefix packages/a test')
  })

  test('no check anywhere: NOTHING_RAN reason, so the approver escalates (S6)', async () => {
    const r = await run({ 'README.md': 'hi', 'src/a.txt': '' })
    expect(r.checks).toEqual([])
    expect(r.reason).toContain(NOTHING_RAN)
  })

  test('scan caps are reported, not silent (S1)', async () => {
    const files: Record<string, string> = {}
    for (let i = 0; i < MAX_DIRS + 20; i++) files[`d${i}/f.txt`] = ''
    const r = await run(files)
    expect(r.warnings.join(' ')).toMatch(/stopped at its limits/)
  })

  test('an option wins over detection', async () => {
    const r = await run({ 'package.json': pkg({ test: 'vitest' }) }, { explicit: 'make verify' })
    expect(argvs(r)).toEqual(['make verify'])
  })

  test('S5: an allowlisted spec command is added, others are dropped', async () => {
    expect(allowedCommand(['python3', 'tools/build_plugin.py', '--check'])).toBe(true)
    expect(allowedCommand(['rm', '-rf', '/'])).toBe(false)
    const r = await run({}, { spec: '## Acceptance criteria\n1. `python3 tools/build_plugin.py --check` exits 0\n2. `rm -rf /` leaves nothing' })
    expect(argvs(r).join('|')).toContain('build_plugin.py --check')
    expect(argvs(r).join('|')).not.toContain('rm -rf')
  })

  test('an unreadable directory is a warning, never an exception', async () => {
    const io = repo({ 'package.json': pkg({ test: 'vitest' }) })
    const bad: ChecksIO = {
      list: async d => {
        if (d !== '/r') throw new Error('EACCES')
        return io.list(d)
      },
      read: io.read,
    }
    const r = await detectProjectChecks(bad, '/r', { touched: ['x/y.ts'] })
    expect(argvs(r)).toContain('npm test')
  })
})
