// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import App from './App'
import type { InitMessage } from './types'

const state = vi.hoisted(() => ({
  initHandler: undefined as ((config: InitMessage) => void) | undefined,
  notifyRendererReady: vi.fn(),
  requestResize: vi.fn(),
  resumeSetup: vi.fn(),
  remindLater: vi.fn(),
  dontRemind: vi.fn(),
}))

vi.mock('./services/bridge', () => ({
  registerInitHandler: (handler: (config: InitMessage) => void) => { state.initHandler = handler },
  registerThemeHandler: () => undefined,
  notifyRendererReady: state.notifyRendererReady,
  requestResize: state.requestResize,
  resumeSetup: state.resumeSetup,
  remindLater: state.remindLater,
  dontRemind: state.dontRemind,
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

const theme = { backgroundPrimary: '#fff', textPrimary: '#000', textSecondary: '#333' }
const fonts = { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' }
const makeConfig = (): InitMessage => ({ theme, fonts })

beforeEach(() => {
  state.notifyRendererReady.mockClear()
  state.requestResize.mockClear()
  state.resumeSetup.mockClear()
  state.remindLater.mockClear()
  state.dontRemind.mockClear()
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    height: 150, width: 320, top: 0, left: 0, bottom: 150, right: 320, x: 0, y: 0, toJSON: () => {},
  } as DOMRect)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 0
  })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<App />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('SetupAssistantResumeToast', () => {
  it('notifies the native host once the renderer mounts', () => {
    expect(state.notifyRendererReady).toHaveBeenCalledOnce()
  })

  it('shows the resume copy and reports its measured height after init', () => {
    act(() => state.initHandler!(makeConfig()))

    expect(container.textContent).toContain('Want to resume your setup?')
    expect(state.requestResize).toHaveBeenCalledWith(320, 150)
  })

  it('reports the measured height only once even if re-initialized', () => {
    act(() => state.initHandler!(makeConfig()))
    act(() => state.initHandler!(makeConfig()))

    expect(state.requestResize).toHaveBeenCalledOnce()
  })

  it('requests resume on "Resume now"', () => {
    act(() => state.initHandler!(makeConfig()))
    const button = [...container.querySelectorAll('button')].find(el => el.textContent === 'Resume now')!
    act(() => button.click())

    expect(state.resumeSetup).toHaveBeenCalledOnce()
  })

  it('requests remind-later on "Remind me later"', () => {
    act(() => state.initHandler!(makeConfig()))
    const button = [...container.querySelectorAll('button')].find(el => el.textContent === 'Remind me later')!
    act(() => button.click())

    expect(state.remindLater).toHaveBeenCalledOnce()
  })

  it("requests dont-remind on \"Don't remind me again\"", () => {
    act(() => state.initHandler!(makeConfig()))
    const button = [...container.querySelectorAll('button')].find(el => el.textContent === "Don't remind me again")!
    act(() => button.click())

    expect(state.dontRemind).toHaveBeenCalledOnce()
  })
})
