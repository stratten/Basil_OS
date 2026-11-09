import { beforeEach, describe, expect, it, vi } from 'vitest'

const bridge = vi.hoisted(() => ({
  available: true,
  resolveSetupHotkeys: vi.fn(),
  applySetupHotkey: vi.fn(),
}))

vi.mock('@/services/bridge', () => ({
  isSetupNativeBridgeAvailable: () => bridge.available,
  resolveSetupHotkeys: bridge.resolveSetupHotkeys,
  applySetupHotkey: bridge.applySetupHotkey,
}))

import { CONTROL_OPTION_C, CONTROL_OPTION_SPACE, OPTION_SPACE, cleanRows, ok } from '@/components/intro/hotkeyTestFixtures'

import { HOTKEYS_FAILED_MESSAGE, HOTKEYS_ITEM_ID, applyNativeExpressItems, nativeHandledItemIds } from './expressNativeHotkeys'

const CHANGE = { id: 'agent_task', title: 'Agent task', from: OPTION_SPACE, to: CONTROL_OPTION_SPACE, reason: 'Siri' }

beforeEach(() => {
  bridge.available = true
  bridge.resolveSetupHotkeys.mockReset()
  bridge.applySetupHotkey.mockReset()
})

describe('nativeHandledItemIds', () => {
  it('lists the hotkey item inside the app and nothing outside it', () => {
    bridge.available = true
    expect(Array.from(nativeHandledItemIds())).toEqual([HOTKEYS_ITEM_ID])
    bridge.available = false
    expect(nativeHandledItemIds().size).toBe(0)
  })

  it('returns the same set every time, so a prop built from it never changes between renders', () => {
    expect(nativeHandledItemIds()).toBe(nativeHandledItemIds())
    bridge.available = false
    expect(nativeHandledItemIds()).toBe(nativeHandledItemIds())
  })
})

describe('applyNativeExpressItems', () => {
  it('does nothing and does not call the app when the hotkey item is not ticked', async () => {
    expect(await applyNativeExpressItems([])).toEqual([])
    expect(await applyNativeExpressItems(['learn_memory'])).toEqual([])
    expect(bridge.resolveSetupHotkeys).not.toHaveBeenCalled()
  })

  it('reports each change in words', async () => {
    bridge.resolveSetupHotkeys.mockResolvedValue(ok({ changes: [CHANGE], unresolved: [] }))
    const results = await applyNativeExpressItems([HOTKEYS_ITEM_ID])
    expect(results).toEqual([
      {
        id: HOTKEYS_ITEM_ID,
        outcome: 'applied',
        message: 'I switched Paprika, agent tasks from ⌥␣ to ⌃⌥␣, because the old keys clashed with Siri. You can change any hotkey in Settings, Hotkeys.',
      },
    ])
  })

  it('reports a skipped item when only leftovers remain', async () => {
    bridge.resolveSetupHotkeys.mockResolvedValue(ok({ changes: [], unresolved: [{ id: 'home_board_toggle', title: 'Open Basil Home', message: 'No free keys.' }] }))
    const [result] = await applyNativeExpressItems([HOTKEYS_ITEM_ID])
    expect(result.outcome).toBe('skipped')
  })

  it('reports a failure for an answer it cannot read', async () => {
    bridge.resolveSetupHotkeys.mockResolvedValue(ok(undefined))
    expect(await applyNativeExpressItems([HOTKEYS_ITEM_ID])).toEqual([
      { id: HOTKEYS_ITEM_ID, outcome: 'failed', message: HOTKEYS_FAILED_MESSAGE },
    ])
  })

  it('never throws: the bridge timeout is replaced with a plain sentence and other errors are passed on', async () => {
    bridge.resolveSetupHotkeys.mockRejectedValueOnce(new Error("Setup action 'resolveSetupHotkeys' did not receive a native response."))
    expect((await applyNativeExpressItems([HOTKEYS_ITEM_ID]))[0]).toEqual({ id: HOTKEYS_ITEM_ID, outcome: 'failed', message: HOTKEYS_FAILED_MESSAGE })

    bridge.resolveSetupHotkeys.mockRejectedValueOnce(new Error("I couldn't read or save your hotkeys just now."))
    expect((await applyNativeExpressItems([HOTKEYS_ITEM_ID]))[0].message).toBe("I couldn't read or save your hotkeys just now.")

    bridge.resolveSetupHotkeys.mockRejectedValueOnce('boom')
    expect((await applyNativeExpressItems([HOTKEYS_ITEM_ID]))[0].message).toBe(HOTKEYS_FAILED_MESSAGE)
  })
})

describe('applyNativeExpressItems with the hotkeys the person chose on the confirm screen', () => {
  const NO_CHANGES = ok({ changes: [], unresolved: [] })

  it('saves a chosen hotkey, keeps it out of the automatic switch, and says so in words', async () => {
    bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: cleanRows() }))
    bridge.resolveSetupHotkeys.mockResolvedValue(NO_CHANGES)

    const results = await applyNativeExpressItems([HOTKEYS_ITEM_ID], {
      hotkeyChoices: { agent_task: { kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: false } },
    })

    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_C, false)
    expect(bridge.resolveSetupHotkeys).toHaveBeenCalledWith(['agent_task'])
    expect(results).toEqual([
      {
        id: HOTKEYS_ITEM_ID,
        outcome: 'applied',
        message: 'I set Paprika, agent tasks to ⌃⌥C, as you chose. You can change any hotkey in Settings, Hotkeys.',
      },
    ])
  })

  it('passes along that the person accepted a clash', async () => {
    bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: cleanRows() }))
    bridge.resolveSetupHotkeys.mockResolvedValue(NO_CHANGES)

    await applyNativeExpressItems([HOTKEYS_ITEM_ID], {
      hotkeyChoices: { conversation_toggle: { kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: true } },
    })

    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('conversation_toggle', CONTROL_OPTION_C, true)
  })

  it('leaves a kept hotkey alone and does not claim that nothing clashed', async () => {
    bridge.resolveSetupHotkeys.mockResolvedValue(NO_CHANGES)

    const [result] = await applyNativeExpressItems([HOTKEYS_ITEM_ID], { hotkeyChoices: { agent_task: { kind: 'keep' } } })

    expect(bridge.applySetupHotkey).not.toHaveBeenCalled()
    expect(bridge.resolveSetupHotkeys).toHaveBeenCalledWith(['agent_task'])
    expect(result.outcome).toBe('skipped')
    expect(result.message).toBe('I left Paprika, agent tasks as it is, as you chose. You can change any hotkey in Settings, Hotkeys.')
  })

  it('still switches the other clashing hotkeys and reports both', async () => {
    bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: cleanRows() }))
    bridge.resolveSetupHotkeys.mockResolvedValue(ok({
      changes: [{ id: 'conversation_toggle', title: 'Toggle conversation', from: OPTION_SPACE, to: CONTROL_OPTION_SPACE, reason: 'this Mac\'s media keys' }],
      unresolved: [],
    }))

    const [result] = await applyNativeExpressItems([HOTKEYS_ITEM_ID], {
      hotkeyChoices: { agent_task: { kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: false } },
    })

    expect(result.outcome).toBe('applied')
    expect(result.message).toContain('I set Paprika, agent tasks to ⌃⌥C, as you chose.')
    expect(result.message).toContain('I switched Toggle conversation from ⌥␣ to ⌃⌥␣')
  })

  it('reports a chosen hotkey the Mac refused or failed to save, and carries on', async () => {
    bridge.applySetupHotkey
      .mockResolvedValueOnce(ok({ saved: false, conflicts: [], rows: cleanRows() }))
      .mockRejectedValueOnce(new Error('boom'))
    bridge.resolveSetupHotkeys.mockResolvedValue(NO_CHANGES)

    const [result] = await applyNativeExpressItems([HOTKEYS_ITEM_ID], {
      hotkeyChoices: {
        agent_task: { kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: false },
        conversation_toggle: { kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: false },
      },
    })

    expect(result.outcome).toBe('skipped')
    expect(result.message).toContain("I couldn't set Paprika, agent tasks to the keys you chose, so I left it as it is.")
    expect(result.message).toContain("I couldn't save the keys you chose for Toggle conversation, so I left it as it is.")
    expect(bridge.resolveSetupHotkeys).toHaveBeenCalledWith(['agent_task', 'conversation_toggle'])
  })

  it('does not exclude anything when nothing was chosen', async () => {
    bridge.resolveSetupHotkeys.mockResolvedValue(NO_CHANGES)
    const [result] = await applyNativeExpressItems([HOTKEYS_ITEM_ID])
    expect(bridge.resolveSetupHotkeys).toHaveBeenCalledWith([])
    expect(result.message).toBe('None of your hotkeys clash with anything on this Mac, so I left them alone.')
  })
})
