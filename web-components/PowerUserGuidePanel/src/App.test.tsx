// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import App from './App'
import type { InitMessage } from './types'

const state = vi.hoisted(() => ({
  initHandler: undefined as ((config: InitMessage) => void) | undefined,
  dismissPanel: vi.fn(),
}))

vi.mock('./services/bridge', () => ({
  registerInitHandler: (handler: (config: InitMessage) => void) => { state.initHandler = handler },
  registerThemeHandler: () => undefined,
  notifyRendererReady: vi.fn(),
  dismissPanel: state.dismissPanel,
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

const config: InitMessage = {
  theme: {
    backgroundPrimary: '#ffffff',
    backgroundSecondary: '#f5f5f7',
    primary: '#0a84ff',
    textPrimary: '#000000',
    textSecondary: '#333333',
  },
  fonts: { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' },
}

beforeEach(() => {
  state.dismissPanel.mockClear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<App />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('PowerUserGuidePanel App', () => {
  it('renders the Transcription section by default once initialized', () => {
    act(() => state.initHandler!(config))

    expect(container.textContent).toContain('Voice Transcription')
    expect(container.textContent).toContain('Transform your voice into text instantly')
  })

  it('switches sections when a sidebar row is selected', () => {
    act(() => state.initHandler!(config))

    const conversationRow = [...container.querySelectorAll<HTMLButtonElement>('.pug-sidebar-row')].find(el => el.textContent?.includes('Conversation'))!
    act(() => conversationRow.click())

    expect(container.textContent).toContain('Basil calls')
    expect(container.textContent).toContain('Dill')
  })

  it('renders the corrected Conversation subtitle describing the capability before the nickname', () => {
    act(() => state.initHandler!(config))
    const conversationRow = [...container.querySelectorAll<HTMLButtonElement>('.pug-sidebar-row')].find(el => el.textContent?.includes('Conversation'))!
    act(() => conversationRow.click())

    const subtitle = container.querySelector('.pug-section-subtitle')!.textContent!
    expect(subtitle.startsWith('An open-ended AI chat')).toBe(true)
    expect(subtitle).toContain('Dill')
    expect(subtitle).toContain('nickname')
  })

  it('dismisses via the footer Done button', () => {
    act(() => state.initHandler!(config))
    const doneButton = [...container.querySelectorAll('button')].find(el => el.textContent === 'Done')!
    act(() => doneButton.click())

    expect(state.dismissPanel).toHaveBeenCalledOnce()
  })
})
