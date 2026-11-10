import { describe, expect, test } from 'claude-code/testing'
import { parseDecision, parseTasks, parseVerdict } from '../hooks/flow'
import { applyRulings } from '../hooks/route'

// Shapes the agents' answers take around the markers the parsers read. A parser that misses a shape
// must fail on the safe side: a PASS stays unproven, a finding stays standing.

describe('parseVerdict: a PASS that lists a blocker/major finding is changes, whatever the finding line looks like', () => {
  const shapes: [string, string][] = [
    ['bold severity', '**[major]** a.ts:1 wrong'],
    ['bullet and bold severity', '- **[major]** a.ts:1 wrong'],
    ['numbered', '1. [major] a.ts:1 wrong'],
    ['numbered with a paren', '1) [major] a.ts:1 wrong'],
    ['numbered and bold', '1. **[major]** a.ts:1 wrong'],
    ['severity word high', '- [high] a.ts:1 wrong'],
    ['severity word critical', '- [critical] a.ts:1 wrong'],
    ['bold critical', '**[critical]** a.ts:1 wrong'],
    ['blocker, numbered', '2. [blocker] a.ts:1 wrong'],
    ['uppercase severity', '- [MAJOR] a.ts:1 wrong'],
  ]
  for (const [name, line] of shapes) {
    test(name, () => {
      const v = parseVerdict(`VERDICT: PASS\nFINDINGS:\n${line}`)
      expect(v.state).toBe('changes')
      expect(v.findings.length).toBe(1)
      expect(v.findings[0]!.where).toBe('a.ts:1')
      expect(v.findings[0]!.severity).not.toBe('minor')
    })
  }

  test('severity words map: critical is a blocker, high a major', () => {
    expect(parseVerdict('VERDICT: CHANGES\n- [critical] a.ts:1 x').findings[0]!.severity).toBe('blocker')
    expect(parseVerdict('VERDICT: CHANGES\n- [high] a.ts:1 x').findings[0]!.severity).toBe('major')
  })

  test('minor and low findings in the new shapes may stand under a pass', () => {
    expect(parseVerdict('VERDICT: PASS\n1. [minor] a.ts:1 name').state).toBe('pass')
    expect(parseVerdict('VERDICT: PASS\n**[minor]** a.ts:1 name').state).toBe('pass')
    expect(parseVerdict('VERDICT: PASS\n- [low] a.ts:1 name').state).toBe('pass')
  })

  test('already working, still working: lowercase and bold verdicts', () => {
    expect(parseVerdict('verdict: pass').state).toBe('pass')
    expect(parseVerdict('**VERDICT: PASS**').state).toBe('pass')
    expect(parseVerdict('**VERDICT:** PASS').state).toBe('pass')
    expect(parseVerdict('VERDICT: **CHANGES**\n- [major] a.ts:1 x').state).toBe('changes')
  })

  test('a continuation line is still part of a numbered finding', () => {
    const v = parseVerdict('VERDICT: CHANGES\n1. [major] a.ts:1 wrong\n   and why')
    expect(v.findings[0]!.text).toBe('wrong and why')
  })
})

describe('parseVerdict: a verdict line naming both options is not a pass', () => {
  for (const line of ['VERDICT: PASS | CHANGES', 'VERDICT: PASS or CHANGES', 'VERDICT: PASS / CHANGES', 'VERDICT: PASS, CHANGES', '**VERDICT:** PASS | CHANGES', 'VERDICT: CHANGES | PASS']) {
    test(line, () => {
      const v = parseVerdict(line)
      expect(v.state).toBe('changes')
      expect(v.findings[0]!.text).toMatch(/no VERDICT/)
    })
  }

  test('a real verdict on another line still counts, and "no changes" after PASS is not an option', () => {
    expect(parseVerdict('VERDICT: PASS | CHANGES\nVERDICT: PASS').state).toBe('pass')
    expect(parseVerdict('VERDICT: PASS - no changes needed').state).toBe('pass')
  })

  test('the same holds for the approver: DECISION: APPROVE | ESCALATE is no decision', () => {
    expect(parseDecision('DECISION: APPROVE | ESCALATE').decision).toBeNull()
    expect(parseDecision('DECISION: APPROVE\nREASON: ok').decision).toBe('APPROVE')
  })
})

describe('applyRulings: the ruling label shapes', () => {
  const f = [
    { severity: 'major' as const, where: 'a.ts:1', text: 'one' },
    { severity: 'major' as const, where: 'b.ts:2', text: 'two' },
  ]
  const no = () => false
  const shapes = ['F1: REFUTED a.ts:1 evidence', '**F1:** REFUTED a.ts:1 evidence', '1. F1: REFUTED a.ts:1 evidence', '`F1`: REFUTED a.ts:1 evidence', '- `F1`: REFUTED a.ts:1 evidence', '1. **F1:** REFUTED a.ts:1 evidence', '1. **`F1`**: **REFUTED** a.ts:1 evidence', '- **F1:** **REFUTED** a.ts:1 evidence', '1) F1: REFUTED a.ts:1 evidence', '**F1: REFUTED** a.ts:1 evidence', '**F1**: REFUTED a.ts:1 evidence', '- F1: REFUTED a.ts:1 evidence', '`F1`: `REFUTED` a.ts:1 evidence']
  for (const line of shapes) {
    test(line, () => {
      const { kept, dropped } = applyRulings(f, `${line}\nF2: STANDS traced`, no)
      expect(dropped.map(d => d.finding)).toEqual([f[0]])
      expect(dropped[0]!.ruling).toBe('refuted')
      expect(dropped[0]!.why).toBe('a.ts:1 evidence')
      expect(kept).toEqual([f[1]])
    })
  }

  test('a miss keeps the finding: prose naming F1, no label, a label with no evidence', () => {
    for (const text of ['The skeptic checked F1 and it is solid.', 'F1 REFUTED a.ts:1 evidence', '**F1:** REFUTED', '`F1` is REFUTED a.ts:1 e']) {
      const { kept, dropped } = applyRulings(f, text, no)
      expect(dropped).toEqual([])
      expect(kept).toEqual(f)
    }
  })

  test('a security blocker is still kept under the new shapes', () => {
    const sec = [{ severity: 'blocker' as const, where: 'a.ts:1', text: 'sqli' }]
    expect(applyRulings(sec, '1. **F1:** REFUTED a.ts:1 evidence', () => true).kept).toEqual(sec)
  })
})

describe('parseTasks: list marker and tag shapes', () => {
  const want = [{ title: 'Add limiter', priority: 'high', dependsOn: [] }]
  for (const line of ['1. [high] Add limiter', '1. **[high]** Add limiter', '- [high] Add limiter', '* [high] Add limiter', '1. [high]: Add limiter', '- **[high]** Add limiter', '1) [HIGH] Add limiter', '**1.** [high] Add limiter']) {
    test(line, () => {
      expect(parseTasks(`TASKS:\n${line}`)).toEqual(want)
    })
  }
  test('needs still read, and lines that are not tasks are skipped', () => {
    expect(parseTasks('TASKS:\n1. **[medium]** B (needs 1 and 2)\nsome prose [high] not a task')).toEqual([{ title: 'B', priority: 'medium', dependsOn: [1, 2] }])
  })
})
