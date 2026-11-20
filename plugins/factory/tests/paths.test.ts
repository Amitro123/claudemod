import { describe, expect, test } from 'claude-code/testing'
import { posix } from './support/posix'

// The invariant: the test engine's file fake gives the same view of a file whatever form of its path the
// engine passes. On Windows the engine hands the hooks `C:\repo\.factory\x` for the `/repo/.factory/x` the
// factory asked for; the fake keys files by the POSIX form, so every form must map to that one key.

describe('posix: one key per file, whatever path form the engine passes', () => {
  const cases: [string, string, string][] = [
    ['Windows absolute path', 'C:\\repo\\.factory\\x', '/repo/.factory/x'],
    ['lowercase drive letter (drive letters are case-insensitive)', 'c:\\repo\\.factory\\x', '/repo/.factory/x'],
    ['already POSIX (Linux CI): must come back unchanged', '/repo/.factory/x', '/repo/.factory/x'],
    ['mixed: the factory appends "/" to a root the engine made with a backslash', 'C:\\repo/.factory/x', '/repo/.factory/x'],
    ['extended-length prefix (what Windows APIs add to long paths)', '\\\\?\\C:\\repo\\.factory\\x', '/repo/.factory/x'],
    ['UNC share: no drive to strip, backslashes still become a slash', '\\\\host\\share\\repo\\x', '//host/share/repo/x'],
    ['a colon inside a name is not a drive: only a leading letter and colon is stripped', '/repo/a:b/x', '/repo/a:b/x'],
  ]
  for (const [why, input, key] of cases) {
    test(why, () => {
      expect(posix(input)).toBe(key)
    })
  }
})
