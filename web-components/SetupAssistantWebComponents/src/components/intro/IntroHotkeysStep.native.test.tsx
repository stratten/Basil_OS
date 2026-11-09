// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const bridge = vi.hoisted(() => ({
  available: true,
  evaluateSetupHotkeys: vi.fn(),
  applySetupHotkey: vi.fn(),
  captureSetupHotkey: vi.fn(),
  cancelSetupHotkeyCapture: vi.fn(),
}))

vi.mock('@/services/bridge', () => ({
  isSetupNativeBridgeAvailable: () => bridge.available,
  evaluateSetupHotkeys: bridge.evaluateSetupHotkeys,
  applySetupHotkey: bridge.applySetupHotkey,
  captureSetupHotkey: bridge.captureSetupHotkey,
  cancelSetupHotkeyCapture: bridge.cancelSetupHotkeyCapture,
  resolveSetupHotkeys: vi.fn(),
}))

import {
  CONTROL_OPTION_C,
  CONTROL_OPTION_SPACE,
  MEDIA_CONFLICT,
  cleanRows,
  clashingRows,
  ok,
  rowsWithAgentTask,
} from './hotkeyTestFixtures'
import { IntroHotkeysStep } from './IntroHotkeysStep'
import { CAPTURE_TIMEOUT_MESSAGE, SAVE_FAILED_MESSAGE } from './useSetupHotkeys'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const USE_SUGGESTION = 'Use ⌃⌥␣'
const CHOOSE = 'Choose different keys'
const KEEP = 'Keep mine'

const DEFAULT_SETTINGS = {
  transcribe_audio: { key: '', enabled: true, modifiers: [], is_double_press: true, double_press_key: 'command' },
  conversation_toggle: { key: 'F8', enabled: true, modifiers: [] },
  assistant_session: { key: '', enabled: true, modifiers: [], is_double_press: true, double_press_key: 'option' },
  agent_task: { key: 'Space', enabled: true, modifiers: ['option'] },
  home_board_toggle: { key: 'B', enabled: false, modifiers: ['control', 'option'] },
}

let container: HTMLElement
let root: Root | null

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(res => { resolve = res })
  return { promise, resolve }
}

async function flush() {
  for (let index = 0; index < 12; index += 1) await Promise.resolve()
}

async function render() {
  await act(async () => {
    root!.render(<IntroHotkeysStep />)
    await flush()
  })
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(element => element.textContent?.trim() === label)
  if (!match) throw new Error(`No button "${label}"`)
  return match
}

async function click(label: string) {
  const target = button(label)
  await act(async () => {
    target.click()
    await flush()
  })
}

function unmountRoot() {
  if (!root) return
  act(() => { root!.unmount() })
  root = null
}

function stubReadOnlyFetch() {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify({ status: 'ok', settings: DEFAULT_SETTINGS }) }))
}

const notice = () => container.querySelector('.intro-hotkey-conflict')
const alertTexts = () => Array.from(container.querySelectorAll('[role="alert"]')).map(element => element.textContent)
const buttonLabels = () => Array.from(container.querySelectorAll('.intro-hotkey-conflict button')).map(element => element.textContent)

beforeEach(() => {
  bridge.available = true
  for (const mock of [bridge.evaluateSetupHotkeys, bridge.applySetupHotkey, bridge.captureSetupHotkey, bridge.cancelSetupHotkeyCapture]) mock.mockReset()
  bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: clashingRows() }))
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  window.basilSetupAssistantConfig = {}
})

afterEach(() => {
  unmountRoot()
  container.remove()
  vi.unstubAllGlobals()
  window.basilSetupAssistantConfig = undefined
})

describe('IntroHotkeysStep with the app', () => {
  it('lists the five hotkeys and explains the one that clashes', async () => {
    await render()

    expect(container.querySelectorAll('.intro-hotkey-row')).toHaveLength(5)
    expect(container.querySelectorAll('.intro-hotkey-conflict')).toHaveLength(1)
    expect(notice()?.textContent).toContain('This clashes with something on your Mac.')
    expect(notice()?.textContent).toContain('Possible clash. Option Space may open Siri.')
    expect(notice()?.textContent).toContain('I suggest ⌃⌥␣ instead.')
    expect(button(USE_SUGGESTION)).toBeTruthy()
    expect(button(CHOOSE)).toBeTruthy()
    expect(button(KEEP)).toBeTruthy()
    expect(container.textContent).not.toContain('Nothing here clashes')
  })

  it('shows rows in setup order whatever order the app answers in', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: [...cleanRows()].reverse() }))
    await render()

    const titles = Array.from(container.querySelectorAll('.intro-hotkey-row dt')).map(element => element.textContent)
    expect(titles).toEqual(['Dill, quick assist', 'Paprika, agent tasks', 'Transcribe audio', 'Toggle conversation', 'Open Basil Home'])
  })

  it('says nothing clashes, shows no clash notice, and offers only a Change keys button per hotkey', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: cleanRows() }))
    await render()

    expect(container.querySelector('.intro-hotkey-clear')?.textContent).toBe('Nothing here clashes with anything on this Mac.')
    const labels = Array.from(container.querySelectorAll('button')).map(element => element.textContent)
    expect(labels).toEqual(['Change keys', 'Change keys', 'Change keys', 'Change keys', 'Change keys'])
    expect(notice()).toBeNull()
  })

  it('lets the person record their own keys for a hotkey that does not clash', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: cleanRows() }))
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: true, binding: CONTROL_OPTION_C }))
    bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: rowsWithAgentTask(CONTROL_OPTION_C) }))
    await render()
    await act(async () => {
      container.querySelector<HTMLButtonElement>('button[aria-label^="Change the keys for Paprika"]')!.click()
      await flush()
    })

    expect(bridge.captureSetupHotkey).toHaveBeenCalledWith('agent_task')
    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_C, false)
    expect(container.querySelector('.intro-hotkey-status')?.textContent).toBe('Saved.')
    expect(container.querySelector('button[aria-label^="Change the keys for Paprika"]')).not.toBeNull()
  })

  it('shows why recording failed on a hotkey that does not clash, and offers another try', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: cleanRows() }))
    bridge.captureSetupHotkey.mockRejectedValue(new Error("Setup action 'captureSetupHotkey' did not receive a native response."))
    await render()
    await act(async () => {
      container.querySelector<HTMLButtonElement>('button[aria-label^="Change the keys for Paprika"]')!.click()
      await flush()
    })

    expect(alertTexts()).toContain(CAPTURE_TIMEOUT_MESSAGE)
    expect(notice()?.textContent).not.toContain('clashes with something')
    expect(button(CHOOSE)).toBeTruthy()
  })

  it('saves the suggested keys with one click', async () => {
    bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: rowsWithAgentTask(CONTROL_OPTION_SPACE) }))
    await render()
    await click(USE_SUGGESTION)

    expect(bridge.applySetupHotkey).toHaveBeenCalledTimes(1)
    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_SPACE, false)
    expect(notice()).toBeNull()
    expect(container.querySelector('.intro-hotkey-status')?.textContent).toBe('Saved.')
    const agentRow = Array.from(container.querySelectorAll('.intro-hotkey-row')).find(element => element.textContent?.includes('Paprika'))
    expect(agentRow?.querySelector('kbd')?.textContent).toBe('⌃⌥␣')
    expect(container.querySelector('.intro-hotkey-clear')).not.toBeNull()
  })

  it('records the person’s own keys and saves them', async () => {
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: true, binding: CONTROL_OPTION_C }))
    bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: rowsWithAgentTask(CONTROL_OPTION_C) }))
    await render()
    await click(CHOOSE)

    expect(bridge.captureSetupHotkey).toHaveBeenCalledWith('agent_task')
    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_C, false)
    expect(container.querySelector('.intro-hotkey-status')?.textContent).toBe('Saved.')
  })

  it('says when recorded keys clash too and saves them only after “Use them anyway”', async () => {
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: true, binding: CONTROL_OPTION_C }))
    bridge.applySetupHotkey
      .mockResolvedValueOnce(ok({ saved: false, conflicts: [MEDIA_CONFLICT], rows: clashingRows() }))
      .mockResolvedValueOnce(ok({ saved: true, conflicts: [], rows: clashingRows() }))
    await render()
    await click(CHOOSE)

    expect(bridge.applySetupHotkey).toHaveBeenCalledTimes(1)
    expect(notice()?.textContent).toContain('Those keys, ⌃⌥C, clash too.')
    expect(notice()?.textContent).toContain('Possible clash. Function keys may act as media keys on this Mac.')

    await click('Use them anyway')

    expect(bridge.applySetupHotkey).toHaveBeenCalledTimes(2)
    expect(bridge.applySetupHotkey).toHaveBeenLastCalledWith('agent_task', CONTROL_OPTION_C, true)
    expect(container.querySelector('.intro-hotkey-status')?.textContent).toContain('Saved. I kept your choice even though it clashes.')
  })

  it('goes back to the suggestion when a recording ends without keys', async () => {
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: false }))
    await render()
    await click(CHOOSE)

    expect(bridge.applySetupHotkey).not.toHaveBeenCalled()
    expect(notice()?.textContent).toContain('I suggest ⌃⌥␣ instead.')
  })

  it('stops a recording on Cancel, tells the app, and ignores keys that arrive afterwards', async () => {
    const capture = deferred<ReturnType<typeof ok>>()
    bridge.captureSetupHotkey.mockReturnValue(capture.promise)
    await render()
    await click(CHOOSE)

    expect(notice()?.textContent).toContain('Press the new keys now.')

    await click('Cancel')
    expect(bridge.cancelSetupHotkeyCapture).toHaveBeenCalledTimes(1)
    expect(notice()?.textContent).toContain('I suggest ⌃⌥␣ instead.')

    await act(async () => {
      capture.resolve(ok({ captured: true, binding: CONTROL_OPTION_C }))
      await flush()
    })
    expect(bridge.applySetupHotkey).not.toHaveBeenCalled()
    expect(notice()?.textContent).toContain('I suggest ⌃⌥␣ instead.')
  })

  it('keeps the person’s keys on “Keep mine” without removing the way to change them here', async () => {
    await render()
    await click(KEEP)

    expect(bridge.applySetupHotkey).not.toHaveBeenCalled()
    expect(container.querySelector('.intro-hotkey-status')?.textContent).toBe('Keeping ⌥␣ for now. You can still choose different keys here, or change it later in Settings, Hotkeys.')
    expect(notice()?.textContent).toContain('I suggest ⌃⌥␣ instead.')
    expect(buttonLabels()).toEqual(expect.arrayContaining([USE_SUGGESTION, CHOOSE, KEEP]))
  })

  it('still lets the person take the suggestion after “Keep mine”', async () => {
    bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: rowsWithAgentTask(CONTROL_OPTION_SPACE) }))
    await render()
    await click(KEEP)
    await click(USE_SUGGESTION)

    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_SPACE, false)
    expect(container.querySelector('.intro-hotkey-status')?.textContent).toBe('Saved.')
    expect(notice()).toBeNull()
  })

  it('shows the app’s message when a save fails and keeps the buttons', async () => {
    bridge.applySetupHotkey.mockRejectedValue(new Error('Could not write the settings file.'))
    await render()
    await click(USE_SUGGESTION)

    expect(alertTexts()).toContain('Could not write the settings file.')
    expect(button(USE_SUGGESTION)).toBeTruthy()
  })

  it('uses a plain sentence when the app answers a save with something unreadable', async () => {
    bridge.applySetupHotkey.mockResolvedValue(ok(undefined))
    await render()
    await click(USE_SUGGESTION)

    expect(alertTexts()).toContain(SAVE_FAILED_MESSAGE)
  })

  it('offers only your own keys or keeping these when no free replacement exists', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: clashingRows(null) }))
    await render()

    expect(notice()?.textContent).toContain("I couldn't find a free replacement")
    expect(Array.from(container.querySelectorAll('.intro-hotkey-conflict button')).map(element => element.textContent)).toEqual([CHOOSE, KEEP])
  })

  it('explains a recording that timed out and tells the app to stop listening', async () => {
    bridge.captureSetupHotkey.mockRejectedValue(new Error("Setup action 'captureSetupHotkey' did not receive a native response."))
    await render()
    await click(CHOOSE)

    expect(alertTexts()).toContain(CAPTURE_TIMEOUT_MESSAGE)
    expect(bridge.cancelSetupHotkeyCapture).toHaveBeenCalledTimes(1)
  })

  it('tells the app to stop listening when the window closes mid-recording', async () => {
    bridge.captureSetupHotkey.mockReturnValue(deferred<ReturnType<typeof ok>>().promise)
    await render()
    await click(CHOOSE)
    expect(bridge.cancelSetupHotkeyCapture).not.toHaveBeenCalled()

    unmountRoot()
    expect(bridge.cancelSetupHotkeyCapture).toHaveBeenCalledTimes(1)
  })

  it('does not tell the app to stop listening on unmount when nothing was recording', async () => {
    await render()
    unmountRoot()
    expect(bridge.cancelSetupHotkeyCapture).not.toHaveBeenCalled()
  })
})

describe('IntroHotkeysStep without the app or when the check fails', () => {
  it('shows the read-only list and never asks the app when the bridge is absent', async () => {
    bridge.available = false
    stubReadOnlyFetch()
    await render()

    expect(bridge.evaluateSetupHotkeys).not.toHaveBeenCalled()
    expect(container.querySelectorAll('.intro-hotkey-row')).toHaveLength(5)
    expect(container.querySelector('.intro-hotkey-conflict')).toBeNull()
    expect(container.textContent).toContain('Settings > Hotkeys')
  })

  it('falls back to the read-only list when the check fails', async () => {
    bridge.evaluateSetupHotkeys.mockRejectedValue(new Error('No native answer.'))
    stubReadOnlyFetch()
    await render()

    expect(container.querySelectorAll('.intro-hotkey-row')).toHaveLength(5)
    expect(container.querySelector('.intro-hotkey-conflict')).toBeNull()
  })

  it('falls back to the read-only list when the answer has no usable rows', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: [] }))
    stubReadOnlyFetch()
    await render()

    expect(container.querySelectorAll('.intro-hotkey-row')).toHaveLength(5)
    expect(container.querySelector('.intro-hotkey-conflict')).toBeNull()
  })

  it('keeps the unchanged keys visible on the read-only fallback', async () => {
    bridge.available = false
    stubReadOnlyFetch()
    await render()

    const first = container.querySelector('.intro-hotkey-row')
    expect(first?.textContent).toContain('⌥⌥ (press twice)')
  })
})
