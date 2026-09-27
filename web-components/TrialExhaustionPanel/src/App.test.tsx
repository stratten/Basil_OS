// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import App from './App'
import type { InitMessage, UseLocalModelsResult } from './types'

const state = vi.hoisted(() => ({
  initHandler: undefined as ((config: InitMessage) => void) | undefined,
  useLocalModelsResultHandler: undefined as ((result: UseLocalModelsResult) => void) | undefined,
  dismissPanel: vi.fn(),
  requestSignUp: vi.fn(),
  requestAddOwnKeys: vi.fn(),
  requestUseLocalModels: vi.fn(),
}))

vi.mock('./services/bridge', () => ({
  registerInitHandler: (handler: (config: InitMessage) => void) => { state.initHandler = handler },
  registerThemeHandler: () => undefined,
  registerUseLocalModelsResultHandler: (handler: (result: UseLocalModelsResult) => void) => { state.useLocalModelsResultHandler = handler },
  notifyRendererReady: vi.fn(),
  dismissPanel: state.dismissPanel,
  requestSignUp: state.requestSignUp,
  requestAddOwnKeys: state.requestAddOwnKeys,
  requestUseLocalModels: state.requestUseLocalModels,
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

const theme = { backgroundPrimary: '#fff', textPrimary: '#000', textSecondary: '#333' }
const fonts = { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' }
const makeConfig = (values: Partial<InitMessage> = {}): InitMessage => ({
  theme,
  fonts,
  remainingBalanceFormatted: '$0.00',
  limitFormatted: '$5.00',
  isAuthenticated: false,
  userEmail: null,
  ...values,
})

beforeEach(() => {
  state.dismissPanel.mockClear()
  state.requestSignUp.mockClear()
  state.requestAddOwnKeys.mockClear()
  state.requestUseLocalModels.mockClear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<App />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('TrialExhaustionPanel', () => {
  it('shows "Sign in to Continue" and the remaining balance for an unauthenticated user', () => {
    act(() => state.initHandler!(makeConfig()))

    expect(container.textContent).toContain('Sign in to Continue')
    expect(container.textContent).toContain('$0.00 remaining of $5.00')
  })

  it('dismisses via the header close button', () => {
    act(() => state.initHandler!(makeConfig()))
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="Dismiss"]')!.click())

    expect(state.dismissPanel).toHaveBeenCalledOnce()
  })

  it('shows "Continue with Basil Cloud" for an authenticated user and requests sign-up on click', () => {
    act(() => state.initHandler!(makeConfig({ isAuthenticated: true, userEmail: 'user@example.com' })))

    const button = [...container.querySelectorAll('button')].find(el => el.textContent === 'Continue with Basil Cloud')!
    act(() => button.click())

    expect(state.requestSignUp).toHaveBeenCalledOnce()
  })

  it('requests adding a provider account key', () => {
    act(() => state.initHandler!(makeConfig()))
    const button = [...container.querySelectorAll('button')].find(el => el.textContent === 'Use Your Own Provider Account')!
    act(() => button.click())

    expect(state.requestAddOwnKeys).toHaveBeenCalledOnce()
  })

  it('requests switching to local models and dismisses once the native side confirms success', () => {
    act(() => state.initHandler!(makeConfig()))
    const button = [...container.querySelectorAll('button')].find(el => el.textContent === 'Use Local Models')!
    act(() => button.click())

    expect(state.requestUseLocalModels).toHaveBeenCalledOnce()
    expect(container.textContent).toContain('Switching…')

    act(() => state.useLocalModelsResultHandler!({ requestId: 'any', status: 'success' }))

    expect(state.dismissPanel).toHaveBeenCalledOnce()
  })
})
