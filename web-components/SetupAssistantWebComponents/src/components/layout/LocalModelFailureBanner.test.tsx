// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupLocalModelFailure } from '@/state/setupAssistantStore'

import { LocalModelFailureBanner } from './LocalModelFailureBanner'

const switchToSmallerReasoningModel = vi.fn()
vi.mock('@/services/api', () => ({
  switchToSmallerReasoningModel: () => switchToSmallerReasoningModel(),
}))

const FAILURE: SetupLocalModelFailure = {
  kind: 'memory',
  message: 'Your Mac ran out of memory while running qwen.gguf.',
  detail: 'llama_decode returned -3 with a context of 32768 tokens',
  actions: [
    { id: 'retry', label: 'Try again' },
    { id: 'smaller_model', label: 'Use a smaller model' },
    { id: 'cloud_or_key', label: 'Use Basil Cloud or an API key' },
    { id: 'show_logs', label: 'Show logs' },
    { id: 'report', label: 'Report a problem' },
  ],
}

let container: HTMLElement
let root: Root

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  switchToSmallerReasoningModel.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

function renderBanner(overrides: Partial<Parameters<typeof LocalModelFailureBanner>[0]> = {}) {
  const props = {
    failure: FAILURE,
    onRetry: vi.fn(),
    onChooseAnotherRoute: vi.fn(),
    onReport: vi.fn(),
    onShowLogs: vi.fn(),
    ...overrides,
  }
  act(() => { root.render(<LocalModelFailureBanner {...props} />) })
  return props
}

function button(label: string): HTMLButtonElement {
  const match = [...container.querySelectorAll('button')].find(element => element.textContent === label)
  if (!match) throw new Error(`No button labeled ${label}`)
  return match as HTMLButtonElement
}

async function flush() {
  await act(async () => { await Promise.resolve() })
}

describe('LocalModelFailureBanner', () => {
  it('shows the plain message and one button per offered action, with the first as primary', () => {
    renderBanner()

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('ran out of memory')
    expect([...container.querySelectorAll('button')].map(element => element.textContent)).toEqual([
      'Try again',
      'Use a smaller model',
      'Use Basil Cloud or an API key',
      'Show logs',
      'Report a problem',
    ])
    expect(button('Try again').className).toBe('primary-button')
    expect(button('Report a problem').className).toBe('secondary-button')
  })

  it('does not show the native return code to the user', () => {
    renderBanner()

    expect(container.textContent).not.toContain('llama_decode')
  })

  it('retries, returns to the model step, and reports with the native detail', () => {
    const props = renderBanner()

    act(() => { button('Try again').click() })
    act(() => { button('Use Basil Cloud or an API key').click() })
    act(() => { button('Show logs').click() })
    act(() => { button('Report a problem').click() })

    expect(props.onRetry).toHaveBeenCalledTimes(1)
    expect(props.onChooseAnotherRoute).toHaveBeenCalledTimes(1)
    expect(props.onReport).toHaveBeenCalledWith('llama_decode returned -3 with a context of 32768 tokens')
    expect(props.onShowLogs).toHaveBeenCalledWith('llama_decode returned -3 with a context of 32768 tokens')
  })

  it('switches to the smaller model and retries automatically when it is already installed', async () => {
    switchToSmallerReasoningModel.mockResolvedValue({ status: 'switched', model_id: 'm', message: 'done' })
    const props = renderBanner()

    act(() => { button('Use a smaller model').click() })
    await flush()

    expect(switchToSmallerReasoningModel).toHaveBeenCalledTimes(1)
    expect(props.onRetry).toHaveBeenCalledTimes(1)
  })

  it('polls while the smaller model downloads, then retries once it is installed', async () => {
    switchToSmallerReasoningModel
      .mockResolvedValueOnce({ status: 'downloading', model_id: 'm', message: 'Downloading a smaller model (2.9GB).' })
      .mockResolvedValueOnce({ status: 'downloading', model_id: 'm', message: 'Downloading a smaller model (2.9GB).' })
      .mockResolvedValueOnce({ status: 'switched', model_id: 'm', message: 'done' })
    const props = renderBanner()

    act(() => { button('Use a smaller model').click() })
    await flush()
    expect(container.querySelector('[role="status"]')?.textContent).toContain('Downloading a smaller model (2.9GB).')
    expect(button('Use a smaller model').disabled).toBe(true)
    expect(props.onRetry).not.toHaveBeenCalled()

    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })

    expect(switchToSmallerReasoningModel).toHaveBeenCalledTimes(3)
    expect(props.onRetry).toHaveBeenCalledTimes(1)
  })

  it('explains when no smaller model exists and offers the other actions again', async () => {
    switchToSmallerReasoningModel.mockResolvedValue({
      status: 'unavailable',
      model_id: null,
      message: 'There is no smaller local model for this one. Use Basil Cloud or your own API key instead.',
    })
    const props = renderBanner()

    act(() => { button('Use a smaller model').click() })
    await flush()

    expect(container.querySelector('[role="status"]')?.textContent).toContain('no smaller local model')
    expect(button('Use a smaller model').disabled).toBe(false)
    expect(props.onRetry).not.toHaveBeenCalled()
  })

  it('shows a request error instead of throwing', async () => {
    switchToSmallerReasoningModel.mockRejectedValue(new Error('Basil could not reach the setup service.'))
    renderBanner()

    act(() => { button('Use a smaller model').click() })
    await flush()

    expect(container.querySelector('[role="status"]')?.textContent).toBe('Basil could not reach the setup service.')
  })

  it('stops polling when it unmounts', async () => {
    switchToSmallerReasoningModel.mockResolvedValue({ status: 'downloading', model_id: 'm', message: 'Downloading.' })
    renderBanner()

    act(() => { button('Use a smaller model').click() })
    await flush()
    act(() => { root.unmount() })
    root = createRoot(container)
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })

    expect(switchToSmallerReasoningModel).toHaveBeenCalledTimes(1)
  })
})
