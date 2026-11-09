// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const api = vi.hoisted(() => ({
  fetchExpressPlan: vi.fn(),
  applyExpressPlan: vi.fn(),
  fetchExpressReceipt: vi.fn(),
  fetchStarterDownloadProgress: vi.fn(),
  selectModelAccess: vi.fn(),
  startLocalModelDownload: vi.fn(),
  copyLocalModelFromNormalBasil: vi.fn(),
}))

const bridge = vi.hoisted(() => ({
  evaluateSetupHotkeys: vi.fn(),
  applySetupHotkey: vi.fn(),
  captureSetupHotkey: vi.fn(),
  cancelSetupHotkeyCapture: vi.fn(),
  resolveSetupHotkeys: vi.fn(),
}))

vi.mock('@/services/api', () => api)
vi.mock('@/services/bridge', () => ({ isSetupNativeBridgeAvailable: () => true, ...bridge }))

import {
  CONTROL_OPTION_C,
  CONTROL_OPTION_SPACE,
  MEDIA_CONFLICT,
  clashingRows,
  cleanRows,
  ok,
} from '@/components/intro/hotkeyTestFixtures'

import { ExpressSetup } from './ExpressSetup'
import { THINKING_DOWNLOADING } from './expressProgressFixtures'
import { makeItem, makePlan, THINKING_MODEL_ID } from './expressTestSupport'

const HOTKEYS_ITEM = makeItem({ id: 'hotkeys', group: 'hotkeys', title: 'Hotkeys', native: true })
const APPLIED = { comfort: 'all_in', thinking_model_id: THINKING_MODEL_ID, results: [] }

let container: HTMLElement
let root: Root
const nativeApplier = vi.fn()

async function settle() {
  await vi.advanceTimersByTimeAsync(0)
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

async function mount() {
  await act(async () => {
    root.render(
      <ExpressSetup
        comfort="all_in"
        isYolo={false}
        nativeHandledIds={new Set(['hotkeys'])}
        nativeApplier={nativeApplier}
        onSelectModelAccess={vi.fn()}
        onFinished={vi.fn()}
        onChooseManual={vi.fn()}
      />,
    )
    await settle()
  })
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.click()
    await settle()
  })
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(element => element.textContent?.trim() === label)
  if (!match) throw new Error(`No button "${label}"`)
  return match
}

function hotkeyRow(title: string): HTMLElement {
  const match = Array.from(container.querySelectorAll<HTMLElement>('.intro-hotkey-row')).find(element => element.textContent?.includes(title))
  if (!match) throw new Error(`No hotkey row containing "${title}"`)
  return match
}

const hotkeysSection = () => container.querySelector<HTMLDetailsElement>('.express-hotkeys')
const agentStatus = () => hotkeyRow('Paprika').querySelector('.intro-hotkey-status')?.textContent

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  for (const mock of [...Object.values(api), ...Object.values(bridge), nativeApplier]) mock.mockReset()
  api.fetchExpressReceipt.mockResolvedValue({ items: [] })
  api.fetchExpressPlan.mockResolvedValue(makePlan({ items: [...makePlan().items, HOTKEYS_ITEM] }))
  api.applyExpressPlan.mockResolvedValue(APPLIED)
  api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)
  bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: clashingRows() }))
  bridge.applySetupHotkey.mockResolvedValue(ok({ saved: true, conflicts: [], rows: cleanRows() }))
  nativeApplier.mockResolvedValue([{ id: 'hotkeys', outcome: 'applied', message: 'Done.' }])
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('Express confirm screen: adjusting hotkeys', () => {
  it('opens the hotkey list by itself when something clashes, names the count, and says what happens by default', async () => {
    await mount()

    const section = hotkeysSection()!
    expect(section.open).toBe(true)
    expect(section.querySelector('summary')?.textContent).toBe('Your hotkeys (1 hotkey clashes with something on this Mac)')
    expect(section.textContent).toContain('Nothing is saved until you press Do it.')
    expect(hotkeyRow('Paprika').textContent).toContain("Unless you choose otherwise, I'll switch it to ⌃⌥␣ when you press Do it.")
    expect(hotkeyRow('Paprika').querySelector('kbd')?.textContent).toBe('⌥␣')
  })

  it('lists every hotkey, closed, when nothing clashes', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: cleanRows() }))
    await mount()

    const section = hotkeysSection()!
    expect(section.open).toBe(false)
    expect(section.querySelector('summary')?.textContent).toBe('Your hotkeys (none clash, but you can change any of them)')
    expect(section.querySelectorAll('.intro-hotkey-row')).toHaveLength(5)
  })

  it('checks a suggestion without saving it, shows the new keys, and holds the choice until Do it', async () => {
    await mount()
    await click(button('Use ⌃⌥␣'))

    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_SPACE, false, true)
    expect(hotkeyRow('Paprika').querySelector('kbd')?.textContent).toBe('⌃⌥␣')
    expect(agentStatus()).toBe('Will change when you press Do it.')
    expect(hotkeysSection()!.querySelector('summary')?.textContent).toBe('Your hotkeys (none clash, but you can change any of them)')
    expect(bridge.resolveSetupHotkeys).not.toHaveBeenCalled()
    expect(nativeApplier).not.toHaveBeenCalled()

    await click(button('Do it'))

    expect(nativeApplier).toHaveBeenCalledWith(['hotkeys'], {
      hotkeyChoices: { agent_task: { kind: 'binding', binding: CONTROL_OPTION_SPACE, acknowledged: false } },
    })
  })

  it('records the person’s own keys, checks them, and holds them', async () => {
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: true, binding: CONTROL_OPTION_C }))
    await mount()
    await click(button('Choose different keys'))

    expect(bridge.captureSetupHotkey).toHaveBeenCalledWith('agent_task')
    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_C, false, true)
    expect(hotkeyRow('Paprika').querySelector('kbd')?.textContent).toBe('⌃⌥C')

    await click(button('Do it'))
    expect(nativeApplier.mock.calls[0][1].hotkeyChoices.agent_task).toEqual({ kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: false })
  })

  it('shows recorded keys that clash and holds them only after “Use them anyway”', async () => {
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: true, binding: CONTROL_OPTION_C }))
    bridge.applySetupHotkey.mockResolvedValueOnce(ok({ saved: false, conflicts: [MEDIA_CONFLICT], rows: clashingRows() }))
    await mount()
    await click(button('Choose different keys'))

    expect(hotkeyRow('Paprika').textContent).toContain('Those keys, ⌃⌥C, clash too.')
    await click(button('Do it'))
    expect(nativeApplier.mock.calls[0][1].hotkeyChoices).toEqual({})
  })

  it('accepts a clashing choice, tells the person it will be kept, and passes the acknowledgment on', async () => {
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: true, binding: CONTROL_OPTION_C }))
    bridge.applySetupHotkey
      .mockResolvedValueOnce(ok({ saved: false, conflicts: [MEDIA_CONFLICT], rows: clashingRows() }))
      .mockResolvedValueOnce(ok({ saved: true, conflicts: [], rows: clashingRows() }))
    await mount()
    await click(button('Choose different keys'))
    await click(button('Use them anyway'))

    expect(bridge.applySetupHotkey).toHaveBeenLastCalledWith('agent_task', CONTROL_OPTION_C, true, true)
    expect(agentStatus()).toBe("Will change when you press Do it. I'll keep your choice even though it clashes.")

    await click(button('Do it'))
    expect(nativeApplier.mock.calls[0][1].hotkeyChoices.agent_task).toEqual({ kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: true })
  })

  it('holds Keep mine as a choice, with every way to change it still on screen', async () => {
    await mount()
    await click(button('Keep mine'))

    expect(agentStatus()).toBe("Keeping ⌥␣. I won't change this one.")
    expect(Array.from(hotkeyRow('Paprika').querySelectorAll('.intro-hotkey-conflict button')).map(element => element.textContent))
      .toEqual(expect.arrayContaining(['Use ⌃⌥␣', 'Choose different keys', 'Keep mine']))

    await click(button('Do it'))
    expect(nativeApplier.mock.calls[0][1].hotkeyChoices).toEqual({ agent_task: { kind: 'keep' } })
  })

  it('lets the person undo a held choice or choose again', async () => {
    await mount()
    await click(button('Use ⌃⌥␣'))

    expect(Array.from(hotkeyRow('Paprika').querySelectorAll('.intro-hotkey-conflict button')).map(element => element.textContent))
      .toEqual(['Choose different keys', 'Undo'])

    await click(button('Undo'))

    expect(hotkeyRow('Paprika').querySelector('kbd')?.textContent).toBe('⌥␣')
    expect(hotkeyRow('Paprika').textContent).toContain("Unless you choose otherwise, I'll switch it to ⌃⌥␣ when you press Do it.")
    await click(button('Do it'))
    expect(nativeApplier.mock.calls[0][1].hotkeyChoices).toEqual({})
  })

  it('hides the rows and says the hotkeys are left alone when the Hotkeys item is unticked, and applies nothing for them', async () => {
    await mount()
    const itemBox = Array.from(container.querySelectorAll<HTMLElement>('.express-item'))
      .find(element => element.textContent?.includes('Hotkeys'))!.querySelector<HTMLInputElement>('input[type="checkbox"]')!
    await click(itemBox)

    expect(hotkeysSection()).toBeNull()
    expect(container.textContent).toContain("Your hotkeys are not part of this setup, so I'll leave them as they are.")

    await click(button('Do it'))
    expect(nativeApplier).not.toHaveBeenCalled()
  })

  it('lets the person change a hotkey that does not clash, and holds it until Do it', async () => {
    bridge.evaluateSetupHotkeys.mockResolvedValue(ok({ rows: cleanRows() }))
    bridge.captureSetupHotkey.mockResolvedValue(ok({ captured: true, binding: CONTROL_OPTION_C }))
    await mount()
    await click(container.querySelector<HTMLButtonElement>('button[aria-label^="Change the keys for Paprika"]')!)

    expect(bridge.applySetupHotkey).toHaveBeenCalledWith('agent_task', CONTROL_OPTION_C, false, true)
    expect(hotkeyRow('Paprika').querySelector('kbd')?.textContent).toBe('⌃⌥C')
    expect(agentStatus()).toBe('Will change when you press Do it.')

    await click(button('Do it'))
    expect(nativeApplier.mock.calls[0][1].hotkeyChoices.agent_task).toEqual({ kind: 'binding', binding: CONTROL_OPTION_C, acknowledged: false })
  })

  it('shows no hotkey list when the check is unavailable', async () => {
    bridge.evaluateSetupHotkeys.mockRejectedValue(new Error('no bridge'))
    await mount()

    expect(hotkeysSection()).toBeNull()
    expect(button('Do it').disabled).toBe(false)
  })
})
