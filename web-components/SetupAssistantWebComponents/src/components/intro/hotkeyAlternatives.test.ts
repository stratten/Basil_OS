import { describe, expect, it } from 'vitest'

import {
  describeNativeBinding,
  describeResolution,
  hotkeyRowTitle,
  parseApplyOutcome,
  parseBinding,
  parseCaptured,
  parseEvaluation,
  parseResolution,
  parseRows,
} from './hotkeyAlternatives'
import { CONTROL_OPTION_C, CONTROL_OPTION_SPACE, DOUBLE_OPTION, OPTION_SPACE, SIRI_CONFLICT, cleanRows } from './hotkeyTestFixtures'

describe('parseBinding', () => {
  it('reads a complete binding and fills the defaults for a short one', () => {
    expect(parseBinding({ key: 'Space', modifiers: ['option'] })).toEqual({
      key: 'Space',
      enabled: true,
      modifiers: ['option'],
      isDoublePress: false,
      doublePressKey: null,
    })
    expect(parseBinding({ key: 'F8', enabled: false, modifiers: [] })?.enabled).toBe(false)
    expect(parseBinding({ key: '', modifiers: [], isDoublePress: true, doublePressKey: 'option' })).toEqual(DOUBLE_OPTION)
  })

  it('rejects anything that is not a binding', () => {
    for (const value of [null, undefined, 'x', 3, [], {}, { modifiers: [] }, { key: 'A', modifiers: 'option' }, { key: 'A', modifiers: [1] }, { key: 5, modifiers: [] }]) {
      expect(parseBinding(value)).toBeNull()
    }
  })
})

describe('parseRows and parseEvaluation', () => {
  it('keeps good rows, drops malformed conflicts and unknown conflict kinds', () => {
    const rows = parseRows([
      {
        id: 'agent_task',
        binding: OPTION_SPACE,
        conflicts: [SIRI_CONFLICT, { ...SIRI_CONFLICT, kind: 'bogus' }, { ...SIRI_CONFLICT, certainty: 'maybe' }, 'junk'],
        alternative: { key: 3 },
      },
      { id: 'broken', binding: 'nope' },
      { id: 7, binding: OPTION_SPACE },
    ])
    expect(rows).toEqual([{ id: 'agent_task', binding: OPTION_SPACE, conflicts: [SIRI_CONFLICT], alternative: null }])
  })

  it('returns null when there is nothing usable', () => {
    expect(parseRows(undefined)).toBeNull()
    expect(parseRows('rows')).toBeNull()
    expect(parseRows([])).toBeNull()
    expect(parseRows([{ id: 1 }])).toBeNull()
    expect(parseEvaluation(undefined)).toBeNull()
    expect(parseEvaluation({})).toBeNull()
  })

  it('reads the rows of an evaluation payload', () => {
    expect(parseEvaluation({ rows: cleanRows() })).toEqual(cleanRows())
  })
})

describe('parseApplyOutcome', () => {
  it('reads a saved and a refused answer', () => {
    expect(parseApplyOutcome({ saved: true, rows: cleanRows() })).toEqual({ saved: true, conflicts: [], rows: cleanRows() })
    expect(parseApplyOutcome({ saved: false, conflicts: [SIRI_CONFLICT], rows: cleanRows() })?.conflicts).toEqual([SIRI_CONFLICT])
  })

  it('rejects an answer without a boolean saved flag or without rows', () => {
    expect(parseApplyOutcome(undefined)).toBeNull()
    expect(parseApplyOutcome({ saved: 'yes', rows: cleanRows() })).toBeNull()
    expect(parseApplyOutcome({ saved: true })).toBeNull()
  })
})

describe('parseCaptured', () => {
  it('returns the pressed keys only when the recording finished', () => {
    expect(parseCaptured({ captured: true, binding: CONTROL_OPTION_C })).toEqual(CONTROL_OPTION_C)
    expect(parseCaptured({ captured: false, binding: CONTROL_OPTION_C })).toBeNull()
    expect(parseCaptured({ captured: true })).toBeNull()
    expect(parseCaptured(undefined)).toBeNull()
  })
})

describe('parseResolution', () => {
  it('reads changes and leftovers and skips malformed items', () => {
    const resolution = parseResolution({
      changes: [
        { id: 'agent_task', title: 'Agent task', from: OPTION_SPACE, to: CONTROL_OPTION_SPACE, reason: 'Siri' },
        { id: 'agent_task', title: 'Agent task', from: OPTION_SPACE, reason: 'missing to' },
        'junk',
      ],
      unresolved: [{ id: 'home_board_toggle', title: 'Open Basil Home', message: 'No free keys.' }, { id: 4 }],
    })
    expect(resolution).toEqual({
      changes: [{ id: 'agent_task', title: 'Agent task', from: OPTION_SPACE, to: CONTROL_OPTION_SPACE, reason: 'Siri' }],
      unresolved: [{ id: 'home_board_toggle', title: 'Open Basil Home', message: 'No free keys.' }],
    })
  })

  it('accepts two empty lists and rejects a payload without both lists', () => {
    expect(parseResolution({ changes: [], unresolved: [] })).toEqual({ changes: [], unresolved: [] })
    expect(parseResolution(undefined)).toBeNull()
    expect(parseResolution({ changes: [] })).toBeNull()
    expect(parseResolution({ unresolved: [] })).toBeNull()
  })
})

describe('describeNativeBinding and hotkeyRowTitle', () => {
  it('writes keys the way the Hotkeys page does', () => {
    expect(describeNativeBinding(CONTROL_OPTION_SPACE)).toBe('⌃⌥␣')
    expect(describeNativeBinding(DOUBLE_OPTION)).toBe('⌥⌥ (press twice)')
  })

  it('returns null for a missing, disabled or empty binding', () => {
    expect(describeNativeBinding(null)).toBeNull()
    expect(describeNativeBinding(undefined)).toBeNull()
    expect(describeNativeBinding({ ...OPTION_SPACE, enabled: false })).toBeNull()
    expect(describeNativeBinding({ key: '', enabled: true, modifiers: [], isDoublePress: false, doublePressKey: null })).toBeNull()
  })

  it('uses setup titles and falls back for an unknown id', () => {
    expect(hotkeyRowTitle('agent_task', 'Agent task')).toBe('Paprika, agent tasks')
    expect(hotkeyRowTitle('capture_screen', 'Capture screen')).toBe('Capture screen')
  })
})

describe('describeResolution', () => {
  it('names each change, its old and new keys and its reason', () => {
    const result = describeResolution({
      changes: [{ id: 'agent_task', title: 'Agent task', from: OPTION_SPACE, to: CONTROL_OPTION_SPACE, reason: 'Siri' }],
      unresolved: [],
    })
    expect(result).toEqual({
      outcome: 'applied',
      message: 'I switched Paprika, agent tasks from ⌥␣ to ⌃⌥␣, because the old keys clashed with Siri. You can change any hotkey in Settings, Hotkeys.',
    })
  })

  it('is skipped when it could only report keys it could not fix', () => {
    const result = describeResolution({
      changes: [],
      unresolved: [{ id: 'home_board_toggle', title: 'Open Basil Home', message: 'No free keys.' }],
    })
    expect(result).toEqual({
      outcome: 'skipped',
      message: "I couldn't find a free shortcut for Open Basil Home, so I left it as it is. You can change any hotkey in Settings, Hotkeys.",
    })
  })

  it('says so when nothing clashed', () => {
    expect(describeResolution({ changes: [], unresolved: [] })).toEqual({
      outcome: 'applied',
      message: 'None of your hotkeys clash with anything on this Mac, so I left them alone.',
    })
  })

  it('reports a mix of changes and leftovers as applied', () => {
    const result = describeResolution({
      changes: [{ id: 'agent_task', title: 'Agent task', from: OPTION_SPACE, to: CONTROL_OPTION_SPACE, reason: 'Siri' }],
      unresolved: [{ id: 'home_board_toggle', title: 'Open Basil Home', message: 'No free keys.' }],
    })
    expect(result.outcome).toBe('applied')
    expect(result.message).toContain("I couldn't find a free shortcut for Open Basil Home")
  })
})
