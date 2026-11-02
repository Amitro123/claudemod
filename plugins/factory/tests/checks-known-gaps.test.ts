// chk-02: the "not generic enough, skipped files" complaint, as tests of the behaviour we WANT.
// They describe findings S2 and S3 (docs/findings/2026-10-29-factory-run-review.md) and are EXPECTED TO
// FAIL on 0.12.0; gap() inverts them, so CI stays green while the gap exists and goes RED when it is fixed
import { describe, expect, test } from 'claude-code/testing'

import { detectProjectChecks } from '../hooks/checks'
import { pkg, repo } from './support/checks-repo'

// 'claude-code/testing' has no test.failing: gap() passes while the body throws, fails when it stops throwing.
function gap(name: string, body: () => Promise<void>) {
  test(name, async () => {
    let failed = false
    try { await body() } catch { failed = true }
    expect(failed).toBe(true) // false = the gap is fixed: move this test to checks-detection.test.ts as a normal test
  })
}

describe('chk-02 known gaps (gap(): green while the gap exists, red when it is fixed)', () => {
  gap('S3: untouched JS packages two levels down (packages/a, services/b) are detected', async () => {
    const files = {
      'packages/a/package.json': pkg({ test: 'jest' }), 'packages/a/node_modules/x/i.js': '',
      'services/b/package.json': pkg({ test: 'jest' }), 'services/b/node_modules/x/i.js': '',
    }
    const r = await detectProjectChecks(repo(files), '/r', {})
    expect(r.checks.length).toBe(2)
  })

  gap('S2: a subdirectory package.json without node_modules is reported as skipped, not silently dropped', async () => {
    const files = { 'web/package.json': pkg({ test: 'jest' }), 'api/tests/test_x.py': '' }
    const r = await detectProjectChecks(repo(files), '/r', {})
    expect(r.warnings.join(' ')).toMatch(/skipp|not installed/i)
  })

  gap('S3: nested Go and Rust modules two levels down are detected', async () => {
    const files = { 'libs/g/go.mod': 'module g', 'libs/r/Cargo.toml': '[package]' }
    const r = await detectProjectChecks(repo(files), '/r', {})
    expect(r.checks.length).toBe(2)
  })

  gap('S1: python tests four levels down (MAX_DEPTH is 3) are detected, or the cut-off is reported', async () => {
    const r = await detectProjectChecks(repo({ 'tools/x/y/tests/test_deep.py': '' }), '/r', {})
    expect(r.checks.length > 0 || /depth|limit|skipp/i.test(r.warnings.join(' '))).toBe(true)
  })
})
