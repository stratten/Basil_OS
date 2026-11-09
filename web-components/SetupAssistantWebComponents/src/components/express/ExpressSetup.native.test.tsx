// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, type ComponentProps } from 'react'
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

vi.mock('@/services/api', () => api)

import { ExpressSetup } from './ExpressSetup'
import { THINKING_DOWNLOADING } from './expressProgressFixtures'
import { makeItem, makePlan, THINKING_MODEL_ID } from './expressTestSupport'

const HOTKEYS_ITEM = makeItem({ id: 'hotkeys', group: 'hotkeys', title: 'Hotkeys', native: true })
const SWITCHED = 'I switched Paprika, agent tasks from ⌥␣ to ⌃⌥␣, because the old keys clashed with Siri.'

const APPLIED = {
  comfort: 'all_in',
  thinking_model_id: THINKING_MODEL_ID,
  results: [
    { id: 'download_thinking_model', outcome: 'started', message: 'Started downloading Qwen 3.5 9B.' },
    { id: 'learn_memory', outcome: 'applied', message: 'Memory after tasks is on.' },
  ],
}

let container: HTMLElement
let root: Root

const nativeApplier = vi.fn()

async function mount(props: Partial<ComponentProps<typeof ExpressSetup>> = {}) {
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
        {...props}
      />,
    )
    await vi.advanceTimersByTimeAsync(0)
  })
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.click()
    await vi.advanceTimersByTimeAsync(0)
  })
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(element => element.textContent === label)
  if (!match) throw new Error(`No button "${label}"`)
  return match
}

function checkbox(title: string): HTMLInputElement {
  const match = Array.from(container.querySelectorAll<HTMLElement>('.express-item')).find(element => element.textContent?.includes(title))
  if (!match) throw new Error(`No item containing "${title}"`)
  return match.querySelector<HTMLInputElement>('input[type="checkbox"]')!
}

const heading = () => container.querySelector('h2')?.textContent
const resultTexts = () => Array.from(container.querySelectorAll('.express-result')).map(element => element.textContent ?? '')

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  for (const mock of [...Object.values(api), nativeApplier]) mock.mockReset()
  api.fetchExpressReceipt.mockResolvedValue({ items: [] })
  api.fetchExpressPlan.mockResolvedValue(makePlan({ items: [...makePlan().items, HOTKEYS_ITEM] }))
  api.applyExpressPlan.mockResolvedValue(APPLIED)
  api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)
  nativeApplier.mockResolvedValue([{ id: 'hotkeys', outcome: 'applied', message: SWITCHED }])
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('ExpressSetup native items', () => {
  it('runs the native applier after the backend, with only the native ids, and shows its sentence after the backend results', async () => {
    const order: string[] = []
    api.applyExpressPlan.mockImplementation(async () => {
      order.push('backend')
      return APPLIED
    })
    nativeApplier.mockImplementation(async () => {
      order.push('native')
      return [{ id: 'hotkeys', outcome: 'applied', message: SWITCHED }]
    })

    await mount()
    expect(checkbox('Hotkeys').checked).toBe(true)
    await click(button('Do it'))

    expect(order).toEqual(['backend', 'native'])
    expect(nativeApplier).toHaveBeenCalledTimes(1)
    expect(nativeApplier).toHaveBeenCalledWith(['hotkeys'], { hotkeyChoices: {} })
    expect(api.applyExpressPlan.mock.calls[0][1]).toContain('hotkeys')
    expect(heading()).toBe('Getting this Mac ready.')
    const texts = resultTexts()
    expect(texts[texts.length - 1]).toContain(SWITCHED)
    expect(texts[0]).toContain('Memory after tasks is on.')
  })

  it('shows a failed native item as an alert', async () => {
    nativeApplier.mockResolvedValue([{ id: 'hotkeys', outcome: 'failed', message: "I couldn't check your hotkeys. You can look at them in Settings, Hotkeys." }])

    await mount()
    await click(button('Do it'))

    const alert = container.querySelector('.express-result--failed')
    expect(alert?.getAttribute('role')).toBe('alert')
    expect(alert?.textContent).toContain("I couldn't check your hotkeys.")
  })

  it('does not run the native applier when the item is unticked', async () => {
    await mount()
    await click(checkbox('Hotkeys'))
    await click(button('Do it'))

    expect(nativeApplier).not.toHaveBeenCalled()
    expect(api.applyExpressPlan.mock.calls[0][1]).not.toContain('hotkeys')
  })

  it('does not run the native applier when the backend fails, so no hotkey changes without the rest', async () => {
    api.applyExpressPlan.mockRejectedValue(new Error('Backend down'))

    await mount()
    await click(button('Do it'))

    expect(nativeApplier).not.toHaveBeenCalled()
    expect(heading()).not.toBe('Getting this Mac ready.')
  })

  it('hides the item and never runs the applier when the app cannot act on it', async () => {
    await mount({ nativeHandledIds: undefined })
    expect(container.textContent).not.toContain('Hotkeys')

    await click(button('Do it'))
    expect(nativeApplier).not.toHaveBeenCalled()
    expect(api.applyExpressPlan.mock.calls[0][1]).not.toContain('hotkeys')
  })
})
