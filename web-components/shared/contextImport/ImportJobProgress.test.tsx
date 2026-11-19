// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ImportStage } from './contextImportClient'
import { ImportJobProgress } from './ImportJobProgress'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

interface Overrides {
  kind?: 'records' | 'profile'
  phase?: 'starting' | 'running'
  message?: string
  done?: number
  total?: number
  stage?: ImportStage
  tokensWritten?: number
  thinking?: string
  onCancel?: () => void
}

function show(overrides: Overrides = {}) {
  act(() => {
    root.render(
      <ImportJobProgress kind="profile" phase="running" message="Reading part 1 of 2." done={0} total={2} stage="reading" tokensWritten={0} thinking="" onCancel={vi.fn()} {...overrides} />,
    )
  })
}

const stageStates = () => [...container.querySelectorAll('.context-import-stage')].map(item => `${item.textContent}:${item.className.split('--')[1]}`)
const progressValue = () => Number(container.querySelector('[role="progressbar"]')!.getAttribute('aria-valuenow'))

beforeEach(() => {
  vi.useFakeTimers()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
})

describe('ImportJobProgress', () => {
  it('lists the four profile stages and marks earlier ones done, the current one active, and later ones pending', () => {
    show({ stage: 'combining' })

    expect(stageStates()).toEqual([
      'Getting the model ready:done',
      'Reading your text:done',
      'Combining what it learned:active',
      'Writing your profile:pending',
    ])
    expect(container.querySelector('[aria-current="step"]')!.textContent).toBe('Combining what it learned')
  })

  it('lists only loading and reading for a records import', () => {
    show({ kind: 'records', stage: 'loading', phase: 'starting', message: 'Starting.' })

    expect(stageStates()).toEqual(['Getting the model ready:active', 'Reading your text:pending'])
  })

  it('moves the bar forward with the stage and with the parts read, and never leaves it empty', () => {
    show({ stage: 'loading', done: 0 })
    const atLoading = progressValue()
    show({ stage: 'reading', done: 0 })
    const atReadingStart = progressValue()
    show({ stage: 'reading', done: 1, total: 2 })
    const halfwayThroughReading = progressValue()
    show({ stage: 'writing', done: 2 })
    const atWriting = progressValue()

    expect(atLoading).toBeGreaterThan(0)
    expect(atReadingStart).toBeGreaterThan(atLoading)
    expect(halfwayThroughReading).toBeGreaterThan(atReadingStart)
    expect(atWriting).toBeGreaterThan(halfwayThroughReading)
    expect(atWriting).toBeLessThanOrEqual(100)
  })

  it('shows the message with the part count only while reading', () => {
    show({ stage: 'reading', message: 'Read part 1 of 2.', done: 1, total: 2 })
    expect(container.textContent).toContain('Read part 1 of 2. (1 of 2)')

    show({ stage: 'writing', message: 'Writing your profile.', done: 2, total: 2 })
    expect(container.textContent).toContain('Writing your profile.')
    expect(container.textContent).not.toContain('(2 of 2)')
  })

  it('counts the time worked and shows a reassurance only after twenty seconds', async () => {
    show()
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).toContain('Working for 0:00.')
    expect(container.querySelector('[data-testid="context-import-reassurance"]')).toBeNull()

    await act(async () => { await vi.advanceTimersByTimeAsync(19_000) })
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).toContain('Working for 0:19.')
    expect(container.querySelector('[data-testid="context-import-reassurance"]')).toBeNull()

    await act(async () => { await vi.advanceTimersByTimeAsync(66_000) })
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).toContain('Working for 1:25.')
    expect(container.querySelector('[data-testid="context-import-reassurance"]')!.textContent).toContain('nothing leaves this Mac')
  })

  it('says roughly how many words the model has written once it has written any', () => {
    show({ tokensWritten: 0 })
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).not.toContain('words')

    show({ tokensWritten: 1000 })
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).toContain('about 750 words so far')

    show({ tokensWritten: 40 })
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).toContain('about 30 words so far')
  })

  it('disables Cancel before the job exists and once it is stopping, and calls it otherwise', () => {
    const onCancel = vi.fn()
    show({ phase: 'starting', onCancel })
    expect(container.querySelector<HTMLButtonElement>('.secondary-button')!.disabled).toBe(true)

    show({ message: 'Stopping.', onCancel })
    expect(container.querySelector<HTMLButtonElement>('.secondary-button')!.textContent).toBe('Stopping...')
    expect(container.querySelector<HTMLButtonElement>('.secondary-button')!.disabled).toBe(true)

    show({ onCancel })
    act(() => { container.querySelector<HTMLButtonElement>('.secondary-button')!.click() })
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('shows what the model is thinking in a labeled log, and drops the word count while it does', () => {
    show({ tokensWritten: 1000, thinking: 'The note says she lives in Boston.\nNow the date style.' })

    const log = container.querySelector('[data-testid="context-import-thinking"]')!
    expect(log.getAttribute('role')).toBe('log')
    expect(log.textContent).toBe('The note says she lives in Boston.\nNow the date style.')
    expect(document.getElementById(log.getAttribute('aria-labelledby')!)?.textContent).toBe('What the model is thinking')
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).not.toContain('words')
  })

  it('shows no thinking panel when the model streams nothing, and keeps the word count', () => {
    show({ tokensWritten: 1000, thinking: '' })

    expect(container.querySelector('[data-testid="context-import-thinking"]')).toBeNull()
    expect(container.textContent).not.toContain('What the model is thinking')
    expect(container.querySelector('[data-testid="context-import-elapsed"]')!.textContent).toContain('about 750 words so far')
  })

  it('follows the newest words by scrolling the panel to the end when the text changes', () => {
    show({ thinking: 'First stretch.' })
    const log = container.querySelector<HTMLElement>('[data-testid="context-import-thinking"]')!
    Object.defineProperty(log, 'scrollHeight', { value: 480, configurable: true })

    show({ thinking: 'First stretch. Second stretch.' })

    expect(log.scrollTop).toBe(480)
  })
})
