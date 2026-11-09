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
import { makeItem, makePlan, THINKING_MODEL_ID } from './expressTestSupport'
import {
  LOCAL_ACCESS_RESOLVED,
  THINKING_COMPLETED,
  THINKING_DOWNLOADING,
  THINKING_FAILED,
} from './expressProgressFixtures'
import { FAILED_DOWNLOAD_MESSAGE, NO_THINKING_MODEL_MESSAGE } from './useExpressRoute'

const APPLIED = {
  comfort: 'all_in',
  thinking_model_id: THINKING_MODEL_ID,
  results: [
    { id: 'download_thinking_model', outcome: 'started', message: 'Started downloading Qwen 3.5 9B.' },
    { id: 'learn_memory', outcome: 'applied', message: 'Memory after tasks is on.' },
    { id: 'capture_activity', outcome: 'failed', message: "I couldn't turn on Activity Capture. You can turn it on in Settings, General, Home." },
  ],
}

let container: HTMLElement
let root: Root

const onSelect = vi.fn()
const onFinished = vi.fn()
const onChooseManual = vi.fn()

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function mount(props: Partial<ComponentProps<typeof ExpressSetup>> = {}) {
  await act(async () => {
    root.render(
      <ExpressSetup
        comfort="all_in"
        isYolo={false}
        onSelectModelAccess={onSelect}
        onFinished={onFinished}
        onChooseManual={onChooseManual}
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

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(element => element.textContent === label)
  if (!match) throw new Error(`No button "${label}"`)
  return match
}

function ariaButton(label: string): HTMLButtonElement {
  const match = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
  if (!match) throw new Error(`No button labeled "${label}"`)
  return match
}

function checkbox(title: string): HTMLInputElement {
  const match = Array.from(container.querySelectorAll<HTMLElement>('.express-item')).find(element => element.textContent?.includes(title))
  if (!match) throw new Error(`No item containing "${title}"`)
  return match.querySelector<HTMLInputElement>('input[type="checkbox"]')!
}

const heading = () => container.querySelector('h2')?.textContent
const alerts = () => Array.from(container.querySelectorAll('[role="alert"]')).map(element => element.textContent)

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  for (const mock of Object.values(api)) mock.mockReset()
  api.fetchExpressReceipt.mockResolvedValue({ items: [] })
  for (const mock of [onSelect, onFinished, onChooseManual]) mock.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('ExpressSetup loading and review', () => {
  it('shows a checking screen, then the review for the chosen comfort level', async () => {
    const plan = deferred<ReturnType<typeof makePlan>>()
    api.fetchExpressPlan.mockReturnValue(plan.promise)

    await mount()
    expect(heading()).toBe('Checking this Mac.')
    expect(api.fetchExpressPlan).toHaveBeenCalledWith('all_in')

    await act(async () => {
      plan.resolve(makePlan())
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(heading()).toBe("Here is what I'll do on this Mac.")
    expect(container.querySelector('details')!.open).toBe(false)
  })

  it('asks for the plan for the comfort level it was given', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan({ comfort: 'cautious' }))

    await mount({ comfort: 'cautious' })

    expect(api.fetchExpressPlan).toHaveBeenCalledWith('cautious')
    expect(container.querySelector('.eyebrow')!.textContent).toBe('Cautious setup')
  })

  it('shows the YOLO heading on the YOLO path', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())

    await mount({ isYolo: true })

    expect(container.querySelector('.eyebrow')!.textContent).toBe('Everything')
  })

  it('shows a load failure with Try again and a way to the step-by-step flow', async () => {
    api.fetchExpressPlan.mockRejectedValueOnce(new Error('The setup service is not running.')).mockResolvedValue(makePlan())

    await mount()

    expect(heading()).toBe("I couldn't check this Mac.")
    expect(alerts()).toEqual(['The setup service is not running.'])

    await click(button('Set it up step by step instead'))
    expect(onChooseManual).toHaveBeenCalledTimes(1)

    await click(button('Try again'))
    expect(api.fetchExpressPlan).toHaveBeenCalledTimes(2)
    expect(heading()).toBe("Here is what I'll do on this Mac.")
  })

  it('rechecks in place: the review stays on screen while it checks, then drops the warning', async () => {
    const blocked = makePlan({ preflight: [{ id: 'network', ok: false, message: "I can't reach the download server." }] })
    const recheck = deferred<ReturnType<typeof makePlan>>()
    api.fetchExpressPlan.mockResolvedValueOnce(blocked).mockReturnValueOnce(recheck.promise)

    await mount()
    await click(button('Check again'))

    expect(heading()).toBe("Here is what I'll do on this Mac.")
    expect(button('Checking…').disabled).toBe(true)

    await act(async () => {
      recheck.resolve(makePlan())
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(container.querySelector('.express-check-again')).toBeNull()
    expect(api.fetchExpressPlan).toHaveBeenCalledTimes(2)
  })
})

describe('ExpressSetup applying', () => {
  it('sends only the ticked item ids', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount()
    await click(checkbox('Voice Listener'))
    await click(button('Do it'))

    expect(api.applyExpressPlan).toHaveBeenCalledWith('all_in', ['download_thinking_model', 'learn_memory', 'capture_activity'])
  })

  it('sends every selected item when nothing is unticked', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount()
    await click(button('Do it'))

    expect(api.applyExpressPlan).toHaveBeenCalledWith('all_in', ['download_thinking_model', 'learn_memory', 'capture_activity', 'voice_listener'])
  })

  it('sends an empty list when everything is unticked, and still moves on', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue({ comfort: 'all_in', thinking_model_id: null, results: [] })

    await mount()
    for (const title of ['Thinking model', 'Memory after tasks', 'Activity Capture', 'Voice Listener']) {
      await click(checkbox(title))
    }
    await click(button('Do it'))

    expect(api.applyExpressPlan).toHaveBeenCalledWith('all_in', [])
    expect(heading()).toBe('Getting this Mac ready.')
  })

  it('hides a native item the app cannot act on and never sends it', async () => {
    const hotkeys = makeItem({ id: 'hotkeys', group: 'hotkeys', title: 'Hotkeys', native: true })
    api.fetchExpressPlan.mockResolvedValue(makePlan({ items: [...makePlan().items, hotkeys] }))
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount()
    expect(container.textContent).not.toContain('Hotkeys')

    await click(button('Do it'))
    expect(api.applyExpressPlan.mock.calls[0][1]).not.toContain('hotkeys')
  })

  it('shows and sends a native item once the app can act on it', async () => {
    const hotkeys = makeItem({ id: 'hotkeys', group: 'hotkeys', title: 'Hotkeys', native: true })
    api.fetchExpressPlan.mockResolvedValue(makePlan({ items: [...makePlan().items, hotkeys] }))
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount({ nativeHandledIds: new Set(['hotkeys']) })
    expect(checkbox('Hotkeys').checked).toBe(true)

    await click(button('Do it'))
    expect(api.applyExpressPlan.mock.calls[0][1]).toContain('hotkeys')
  })

  it('sends one request when Do it is pressed twice while the first is in flight', async () => {
    const request = deferred<typeof APPLIED>()
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockReturnValue(request.promise)
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount()
    await click(button('Do it'))
    expect(button('Working…').disabled).toBe(true)
    await click(button('Working…'))

    expect(api.applyExpressPlan).toHaveBeenCalledTimes(1)

    await act(async () => {
      request.resolve(APPLIED)
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(heading()).toBe('Getting this Mac ready.')
  })

  it('keeps the review and shows the message when applying fails, then lets the person try again', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan
      .mockRejectedValueOnce(new Error('Downloads are not ready yet. Try again in a moment.'))
      .mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount()
    await click(button('Do it'))

    expect(heading()).toBe("Here is what I'll do on this Mac.")
    expect(alerts()).toEqual(['Downloads are not ready yet. Try again in a moment.'])
    expect(button('Do it').disabled).toBe(false)

    await click(button('Do it'))
    expect(heading()).toBe('Getting this Mac ready.')
  })
})

describe('ExpressSetup progress', () => {
  async function applyAndShowProgress(progress: unknown) {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValue(progress)
    await mount()
    await click(button('Do it'))
  }

  it('lists what was done without repeating the download that already has a progress row', async () => {
    await applyAndShowProgress(THINKING_DOWNLOADING)

    const results = Array.from(container.querySelectorAll('.express-result'))
    expect(results.map(result => result.textContent)).toEqual([
      'DoneMemory after tasks is on.',
      "Needs attentionI couldn't turn on Activity Capture. You can turn it on in Settings, General, Home.",
    ])
    expect(results[1].getAttribute('role')).toBe('alert')
    expect(container.querySelector('.download-progress__percent')!.textContent).toBe('40%')
    expect(container.querySelector('[role="progressbar"]')!.getAttribute('aria-valuenow')).toBe('40')
  })

  it('holds Continue until the thinking model is downloaded and confirmed, then finishes', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValueOnce(THINKING_DOWNLOADING).mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)

    await mount()
    await click(button('Do it'))

    const continueButton = () => container.querySelector<HTMLButtonElement>('.express-continue')!
    expect(heading()).toBe('Getting this Mac ready.')
    expect(continueButton().disabled).toBe(true)
    expect(container.textContent).toContain("I'll let you continue as soon as the thinking model has finished downloading.")

    await advance(2000)

    expect(api.selectModelAccess).toHaveBeenCalledWith({ mode: 'local', local_model_id: THINKING_MODEL_ID })
    expect(onSelect).toHaveBeenCalledWith(LOCAL_ACCESS_RESOLVED.access)
    expect(heading()).toBe('This Mac is ready.')
    expect(continueButton().disabled).toBe(false)

    await click(continueButton())
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('reads the receipt again when the route state changes', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValueOnce(THINKING_DOWNLOADING).mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)

    await mount()
    await click(button('Do it'))
    const before = api.fetchExpressReceipt.mock.calls.length
    expect(before).toBeGreaterThan(0)

    await advance(2000)

    expect(api.fetchExpressReceipt.mock.calls.length).toBeGreaterThan(before)
  })

  it('points to Settings for importing history and says captures are added one memory at a time', async () => {
    await applyAndShowProgress(THINKING_DOWNLOADING)

    expect(container.textContent).toContain('open Settings, then Personalization, then Personal Context')
    expect(container.textContent).toContain('Captures can be added there one memory at a time.')
  })

  it('keeps Continue locked and offers the manual choice when there is no thinking model', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue({ comfort: 'all_in', thinking_model_id: null, results: [] })

    await mount()
    await click(button('Do it'))

    expect(alerts()).toEqual([NO_THINKING_MODEL_MESSAGE])
    expect(container.querySelector<HTMLButtonElement>('.express-continue')!.disabled).toBe(true)
    expect(api.fetchStarterDownloadProgress).not.toHaveBeenCalled()

    await click(button('Choose how I think instead'))
    expect(onChooseManual).toHaveBeenCalledTimes(1)
  })

  it('shows a failed thinking download, offers Retry on the row, and keeps Continue locked', async () => {
    api.startLocalModelDownload.mockResolvedValue({ model_id: THINKING_MODEL_ID, status: 'queued' })
    await applyAndShowProgress(THINKING_FAILED)

    expect(alerts()).toContain(FAILED_DOWNLOAD_MESSAGE)
    expect(container.querySelector<HTMLButtonElement>('.express-continue')!.disabled).toBe(true)

    await click(ariaButton('Retry Qwen 3.5 9B'))

    expect(api.startLocalModelDownload).toHaveBeenCalledWith('Qwen', 'qwen35-9b-q4km')
  })

  it('recovers after a retry: once the model completes, Continue unlocks', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValueOnce(THINKING_FAILED).mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)
    api.startLocalModelDownload.mockResolvedValue({ model_id: THINKING_MODEL_ID, status: 'queued' })

    await mount()
    await click(button('Do it'))
    expect(container.querySelector<HTMLButtonElement>('.express-continue')!.disabled).toBe(true)

    await click(ariaButton('Retry Qwen 3.5 9B'))
    await advance(2000)

    expect(heading()).toBe('This Mac is ready.')
    expect(container.querySelector<HTMLButtonElement>('.express-continue')!.disabled).toBe(false)
  })

  it('does not call the model route again after unmounting mid-download', async () => {
    api.fetchExpressPlan.mockResolvedValue(makePlan())
    api.applyExpressPlan.mockResolvedValue(APPLIED)
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount()
    await click(button('Do it'))
    const reads = api.fetchStarterDownloadProgress.mock.calls.length

    act(() => { root.unmount() })
    root = createRoot(container)
    await advance(10000)

    expect(api.fetchStarterDownloadProgress).toHaveBeenCalledTimes(reads)
    expect(api.selectModelAccess).not.toHaveBeenCalled()
  })
})
