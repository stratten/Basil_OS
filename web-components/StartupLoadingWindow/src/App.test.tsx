// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import App from './App'
import type { InitMessage } from './types'

const state = vi.hoisted(() => ({
  initHandler: undefined as ((config: InitMessage) => void) | undefined,
  statusHandler: undefined as ((status: { message: string }) => void) | undefined,
  closeWindow: vi.fn(),
  minimizeWindow: vi.fn(),
  collapseWindow: vi.fn(),
  expandWindow: vi.fn(),
  notifyDrawnIn: vi.fn(),
}))

vi.mock('./services/bridge', () => ({
  registerInitHandler: (handler: (config: InitMessage) => void) => { state.initHandler = handler },
  registerThemeHandler: () => undefined,
  registerStatusHandler: (handler: (status: { message: string }) => void) => { state.statusHandler = handler },
  notifyRendererReady: vi.fn(),
  notifyDrawnIn: state.notifyDrawnIn,
  closeWindow: state.closeWindow,
  minimizeWindow: state.minimizeWindow,
  collapseWindow: state.collapseWindow,
  expandWindow: state.expandWindow,
}))

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

const init: InitMessage = {
  theme: { backgroundPrimary: '#ffffff', primary: '#003087', secondary: '#33559b', textPrimary: '#000000', processingBase: '#5b4db0' },
  fonts: { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' },
  message: 'Starting Basil...',
}

beforeEach(() => {
  vi.useFakeTimers()
  state.closeWindow.mockClear()
  state.minimizeWindow.mockClear()
  state.notifyDrawnIn.mockClear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<App />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('StartupLoadingWindow', () => {
  it('shows the braille spinner, status copy, and window controls after init', () => {
    act(() => state.initHandler!(init))

    expect(container.querySelector('.startup-loading-spinner')?.textContent).toBe('⠋')
    expect(container.textContent).toContain('Starting Basil...')
    expect(container.querySelector('.basil-window-title')?.textContent).toBe('Basil')
    expect(container.querySelector('[aria-label="Close window"]')).not.toBeNull()
    expect(container.querySelector('[aria-label="Minimize window"]')).not.toBeNull()
    expect(container.querySelector('[aria-label="Collapse window"]')).not.toBeNull()
    expect(container.querySelector('canvas')).toBeNull()

    act(() => { vi.advanceTimersByTime(100) })
    expect(container.querySelector('.startup-loading-spinner')?.textContent).toBe('⠙')
  })

  it('replaces the status line when Swift sends a later message', () => {
    act(() => state.initHandler!(init))
    act(() => state.statusHandler!({ message: 'Launching interface' }))

    expect(container.textContent).toContain('Launching interface')
    expect(container.textContent).not.toContain('Starting Basil...')
  })

  it('wires close to the native dismiss bridge', () => {
    act(() => state.initHandler!(init))
    act(() => {
      container.querySelector<HTMLButtonElement>('[aria-label="Close window"]')?.click()
    })

    expect(state.closeWindow).toHaveBeenCalledTimes(1)
  })
})
