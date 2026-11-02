// chk-02: the "not generic enough, skipped files" complaint, findings S1-S3
// (docs/findings/2026-10-29-factory-run-review.md). Each test pins what detection does TODAY, the gap
// itself, and says in a comment what it should do. When a fix lands, the test goes red on exactly the
// line that changed: update it to the new behaviour and move it to checks-detection.test.ts.
// (An earlier version caught any exception in the body and called that "the gap still exists", so a
// renamed export or a typo also stayed green.)
import { describe, expect, test } from 'claude-code/testing'

import { detectProjectChecks } from '../hooks/checks'
import { argvs, pkg, repo } from './support/checks-repo'

describe('chk-02 known gaps: what detection does today', () => {
  test('S3: untouched JS packages two levels down (packages/a, services/b) are not detected', async () => {
    const files = {
      'packages/a/package.json': pkg({ test: 'jest' }), 'packages/a/node_modules/x/i.js': '',
      'services/b/package.json': pkg({ test: 'jest' }), 'services/b/node_modules/x/i.js': '',
    }
    const r = await detectProjectChecks(repo(files), '/r', {})
    // Should be: ['npm --prefix packages/a test', 'npm --prefix services/b test'].
    expect(argvs(r)).toEqual([])
  })

  test('S2: a subdirectory package.json without node_modules is dropped without a word', async () => {
    const files = { 'web/package.json': pkg({ test: 'jest' }), 'api/tests/test_x.py': '' }
    const r = await detectProjectChecks(repo(files), '/r', {})
    // The python tests in api/ are found; web/ is skipped.
    expect(argvs(r)).toEqual(['python -m pytest -q api'])
    // Should be: a warning that web/ was skipped because its dependencies aren't installed.
    expect(r.warnings).toEqual([])
  })

  test('S3: Go and Rust modules two levels down are not detected', async () => {
    const files = { 'libs/g/go.mod': 'module g', 'libs/r/Cargo.toml': '[package]' }
    const r = await detectProjectChecks(repo(files), '/r', {})
    // Should be: ['go -C libs/g test ./...', 'cargo test --manifest-path libs/r/Cargo.toml'].
    expect(argvs(r)).toEqual([])
  })

  test('S1: python tests four levels down (MAX_DEPTH is 3) are not found, and the cut-off is not reported', async () => {
    const r = await detectProjectChecks(repo({ 'tools/x/y/tests/test_deep.py': '' }), '/r', {})
    // Should be: a pytest check for tools/, or a warning that the scan stopped at its depth.
    expect(argvs(r)).toEqual([])
    expect(r.warnings).toEqual([])
  })
})
