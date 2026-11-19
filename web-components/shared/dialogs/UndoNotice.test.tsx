// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import UndoNotice from './UndoNotice'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

let container: HTMLDivElement
let root: Root

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

describe('UndoNotice', () => {
  it('shows the message and reports the Undo and close buttons', () => {
    const onAction = vi.fn()
    const onExpire = vi.fn()
    act(() => root.render(<UndoNotice noticeKey={1} message="Dismissed." onAction={onAction} onExpire={onExpire} />))
    expect(container.querySelector('[role="status"]')?.textContent).toContain('Dismissed.')
    act(() => container.querySelector<HTMLButtonElement>('.basil-undo-notice__action')!.click())
    expect(onAction).toHaveBeenCalledTimes(1)
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="Close"]')!.click())
    expect(onExpire).toHaveBeenCalledTimes(1)
  })

  it('expires itself after the duration and not before', () => {
    const onExpire = vi.fn()
    act(() => root.render(<UndoNotice noticeKey={1} message="Dismissed." onAction={vi.fn()} onExpire={onExpire} durationMs={3000} />))
    act(() => { vi.advanceTimersByTime(2999) })
    expect(onExpire).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(2) })
    expect(onExpire).toHaveBeenCalledTimes(1)
  })

  it('restarts the countdown for a new notice and never fires after unmounting', () => {
    const onExpire = vi.fn()
    act(() => root.render(<UndoNotice noticeKey={1} message="One" onAction={vi.fn()} onExpire={onExpire} durationMs={3000} />))
    act(() => { vi.advanceTimersByTime(2500) })
    act(() => root.render(<UndoNotice noticeKey={2} message="Two" onAction={vi.fn()} onExpire={onExpire} durationMs={3000} />))
    act(() => { vi.advanceTimersByTime(2500) })
    expect(onExpire).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(600) })
    expect(onExpire).toHaveBeenCalledTimes(1)
    act(() => root.render(<UndoNotice noticeKey={3} message="Three" onAction={vi.fn()} onExpire={onExpire} durationMs={3000} />))
    act(() => root.unmount())
    root = createRoot(container)
    act(() => { vi.advanceTimersByTime(10000) })
    expect(onExpire).toHaveBeenCalledTimes(1)
  })
})
