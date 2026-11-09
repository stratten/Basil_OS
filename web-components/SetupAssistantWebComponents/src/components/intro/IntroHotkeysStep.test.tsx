// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { describeHotkeyBinding } from './hotkeyDisplay'
import { IntroHotkeysStep } from './IntroHotkeysStep'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const DEFAULTS = {
  transcribe_audio: { key: '', enabled: true, modifiers: [], is_double_press: true, double_press_key: 'command' },
  conversation_toggle: { key: 'F8', enabled: true, modifiers: [] },
  assistant_session: { key: '', enabled: true, modifiers: [], is_double_press: true, double_press_key: 'option' },
  agent_task: { key: 'Space', enabled: true, modifiers: ['option'] },
  home_board_toggle: { key: 'B', enabled: false, modifiers: ['control', 'option'] },
}

let container: HTMLElement
let root: Root

async function render() {
  await act(async () => {
    root.render(<IntroHotkeysStep />)
    await Promise.resolve()
    await Promise.resolve()
  })
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  window.basilSetupAssistantConfig = {}
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
  window.basilSetupAssistantConfig = undefined
})

describe('describeHotkeyBinding', () => {
  it('writes modifiers, double presses and Space the way the Hotkeys page does', () => {
    expect(describeHotkeyBinding(DEFAULTS.agent_task)).toBe('⌥␣')
    expect(describeHotkeyBinding(DEFAULTS.transcribe_audio)).toBe('⌘⌘ (press twice)')
    expect(describeHotkeyBinding({ key: 'B', enabled: true, modifiers: ['control', 'option'] })).toBe('⌃⌥B')
    expect(describeHotkeyBinding(DEFAULTS.conversation_toggle)).toBe('F8')
  })

  it('returns null for a hotkey that is off, empty or missing', () => {
    expect(describeHotkeyBinding(DEFAULTS.home_board_toggle)).toBeNull()
    expect(describeHotkeyBinding({ key: '', enabled: true, modifiers: [] })).toBeNull()
    expect(describeHotkeyBinding(undefined)).toBeNull()
  })
})

describe('IntroHotkeysStep', () => {
  it('lists every hotkey with its keys and says where to change them later', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify({ status: 'ok', settings: DEFAULTS }) }))
    await render()

    const rows = Array.from(container.querySelectorAll('.intro-hotkey-row')).map(row => row.textContent)
    expect(rows).toHaveLength(5)
    expect(rows[0]).toContain('Dill, quick assist')
    expect(rows[0]).toContain('⌥⌥ (press twice)')
    expect(rows[1]).toContain('⌥␣')
    expect(rows[4]).toContain('Off')
    expect(container.textContent).toContain('Settings > Hotkeys')
    expect(container.querySelector('.intro-hotkey-conflicts')).toBeNull()
  })

  it('shows an alert naming the macOS feature when a default hotkey conflicts', async () => {
    window.basilSetupAssistantConfig = {
      systemShortcutConflicts: [{ hotkeyId: 'agent_task', source: 'Siri', certainty: 'possible', message: 'Choose another shortcut.' }],
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify({ status: 'ok', settings: DEFAULTS }) }))
    await render()

    const alert = container.querySelector('.intro-hotkey-conflicts')!
    expect(alert.getAttribute('role')).toBe('alert')
    expect(alert.textContent).toContain('Possible conflict with Siri. Choose another shortcut.')
  })

  it('still explains where to look when the hotkeys cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await render()

    expect(container.querySelectorAll('.intro-hotkey-row')).toHaveLength(0)
    expect(container.textContent).toContain('I couldn’t read your hotkeys right now.')
  })
})
