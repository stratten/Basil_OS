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

  it('renders capability icons instead of emoji in every section', () => {
    act(() => state.initHandler!(config))
    const emoji = /\p{Extended_Pictographic}/u
    const rows = [...container.querySelectorAll<HTMLButtonElement>('.pug-sidebar-row')]
    expect(rows).toHaveLength(7)

    for (const row of rows) {
      expect(row.querySelector('.pug-guide-icon')).not.toBeNull()
      act(() => row.click())
      expect(container.querySelector('.pug-section-header .pug-guide-icon')).not.toBeNull()
      expect(emoji.test(container.textContent ?? '')).toBe(false)
    }
  })

  it('presents the Dill or Paprika guide as a sub-item comparing the two helpers', () => {
    act(() => state.initHandler!(config))
    const rows = [...container.querySelectorAll<HTMLButtonElement>('.pug-sidebar-row')]
    const labels = rows.map(row => row.textContent)
    expect(labels).not.toContain('Voice Comparison')
    const comparisonIndex = labels.indexOf('Dill or Paprika?')
    expect(labels[comparisonIndex - 1]).toBe('Paprika')
    expect(rows[comparisonIndex].classList.contains('pug-sidebar-row--sub')).toBe(true)
    expect(rows[comparisonIndex].querySelectorAll('.pug-guide-icon--pair img')).toHaveLength(2)

    act(() => rows[comparisonIndex].click())

    expect(container.querySelector('.pug-section-header h1')!.textContent).toBe('Dill or Paprika?')
    expect([...container.querySelectorAll('.pug-helper-card h3')].map(el => el.textContent)).toEqual(['Dill', 'Paprika'])
    const tableRows = [...container.querySelectorAll('.pug-table--comparison [role="row"]')].slice(1).map(row =>
      [...row.children].map(cell => cell.textContent),
    )
    expect(tableRows).toContainEqual(['Hotkey', '⌥⌥', '⌥Space'])
    expect(tableRows).toContainEqual(['Extra context', 'Your screen, plus any text you highlight', 'Your screen, plus files and folders you drag in'])
    expect(container.textContent).not.toContain('Manual if needed')
    expect(container.querySelector('.pug-helper-tip')!.textContent).toContain('Not sure?')
  })

  it('dismisses via the footer Done button', () => {
    act(() => state.initHandler!(config))
    const doneButton = [...container.querySelectorAll('button')].find(el => el.textContent === 'Done')!
    act(() => doneButton.click())

    expect(state.dismissPanel).toHaveBeenCalledOnce()
  })
})
