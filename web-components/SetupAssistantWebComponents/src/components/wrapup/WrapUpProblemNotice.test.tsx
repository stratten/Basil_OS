// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupLocalModelFailure } from '@/state/setupAssistantStore'

import { WrapUpProblemNotice, wrapUpProblemFrom, type WrapUpProblemNoticeProps } from './WrapUpProblemNotice'

const MEMORY_FAILURE: SetupLocalModelFailure = {
  kind: 'memory',
  message: 'The local model ran out of memory on this Mac.',
  detail: 'llama_decode returned -3',
  actions: [{ id: 'retry', label: 'Retry model' }],
}

let container: HTMLElement
let root: Root

function render(props: WrapUpProblemNoticeProps) {
  act(() => { root.render(<WrapUpProblemNotice {...props} />) })
}

const buttonLabels = () => [...container.querySelectorAll('button')].map(button => button.textContent)

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('wrapUpProblemFrom', () => {
  it('prefers the typed local model failure and keeps its return code', () => {
    expect(wrapUpProblemFrom(MEMORY_FAILURE, 'Basil could not finish that setup step.')).toEqual({
      message: 'The local model ran out of memory on this Mac.',
      detail: 'llama_decode returned -3',
    })
  })

  it('falls back to the generic error with no return code, trimmed', () => {
    expect(wrapUpProblemFrom(undefined, '  The connection dropped.  ')).toEqual({
      message: 'The connection dropped.',
      detail: null,
    })
  })

  it('reports no problem for a missing or blank error', () => {
    expect(wrapUpProblemFrom(undefined, undefined)).toBeNull()
    expect(wrapUpProblemFrom(undefined, null)).toBeNull()
    expect(wrapUpProblemFrom(undefined, '   ')).toBeNull()
  })
})

describe('WrapUpProblemNotice', () => {
  it('shows the plain message as an alert and never offers Retry', () => {
    render({ problem: { message: MEMORY_FAILURE.message, detail: MEMORY_FAILURE.detail }, onShowLogs: vi.fn(), onReport: vi.fn() })

    expect(container.querySelector('[role="alert"]')!.textContent).toContain('The local model ran out of memory on this Mac.')
    expect(buttonLabels()).toEqual(['Show logs', 'Report a problem'])
    expect(container.textContent).not.toContain('Retry')
  })

  it('passes the return code to both actions', () => {
    const onShowLogs = vi.fn()
    const onReport = vi.fn()
    render({ problem: { message: 'Failed.', detail: 'llama_decode returned -3' }, onShowLogs, onReport })

    act(() => { container.querySelectorAll('button')[0].click() })
    act(() => { container.querySelectorAll('button')[1].click() })

    expect(onShowLogs).toHaveBeenCalledWith('llama_decode returned -3')
    expect(onReport).toHaveBeenCalledWith('llama_decode returned -3')
  })

  it('calls the actions with no detail when the problem has no return code', () => {
    const onReport = vi.fn()
    render({ problem: { message: 'The connection dropped.', detail: null }, onReport })

    act(() => { container.querySelector('button')!.click() })

    expect(onReport).toHaveBeenCalledWith(undefined)
  })

  it('shows only the message when no action is provided', () => {
    render({ problem: { message: 'The connection dropped.', detail: null } })

    expect(container.querySelectorAll('button')).toHaveLength(0)
    expect(container.textContent).toContain('The connection dropped.')
  })
})
