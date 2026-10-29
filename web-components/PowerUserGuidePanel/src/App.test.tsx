// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import App from './App'
import type { HotkeyMap, InitMessage } from './types'

const state = vi.hoisted(() => ({
  initHandler: undefined as ((config: InitMessage) => void) | undefined,
  hotkeysHandler: undefined as ((hotkeys: HotkeyMap) => void) | undefined,
  dismissPanel: vi.fn(),
}))

vi.mock('./services/bridge', () => ({
  registerInitHandler: (handler: (config: InitMessage) => void) => { state.initHandler = handler },
  registerThemeHandler: () => undefined,
  registerHotkeysHandler: (handler: (hotkeys: HotkeyMap) => void) => { state.hotkeysHandler = handler },
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
    expect(rows).toHaveLength(8)

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

  function openSection(label: string) {
    const row = [...container.querySelectorAll<HTMLButtonElement>('.pug-sidebar-row')].find(el => el.textContent?.includes(label))!
    act(() => row.click())
  }

  it('shows the shipped default hotkeys until the app reports the saved ones', () => {
    act(() => state.initHandler!(config))
    expect(container.textContent).toContain('Your hotkey: ⌘⌘ (double-tap Command)')
    expect(container.textContent).toContain('Push-to-talk: hold after the double-tap')
    openSection('Conversation')
    expect(container.textContent).toContain('Your hotkey: F8')
    expect(container.textContent).not.toContain('default:')
  })

  it('names the saved hotkeys in every section that mentions one, and follows later changes', () => {
    act(() => state.initHandler!({
      ...config,
      hotkeys: {
        transcription: { display: 'F5', enabled: true, isDoublePress: false },
        assistantSession: { display: '⌃⌃', enabled: true, isDoublePress: true, doublePressKey: 'control' },
        agentTask: { display: '⌃⌥␣', enabled: true, isDoublePress: false },
        conversation: { display: '⌘F8', enabled: false, isDoublePress: false },
      },
    }))
    expect(container.textContent).toContain('Your hotkey: F5')
    expect(container.textContent).toContain('Push-to-talk: hold the hotkey, release to transcribe')
    expect(container.textContent).not.toContain('⌘⌘')

    openSection('Paprika')
    expect(container.textContent).toContain('Press your Paprika hotkey (⌃⌥Space)')
    expect(container.textContent).toContain('Your hotkey: ⌃⌥Space')
    expect(container.textContent).not.toContain('⌥+Space')

    openSection('Dill')
    expect(container.textContent).toContain('Your hotkey: ⌃⌃ (double-tap Control)')

    openSection('Conversation')
    expect(container.textContent).toContain('Your hotkey: ⌘F8 (currently turned off in Settings → Hotkeys)')

    openSection('Dill or Paprika?')
    expect(container.querySelector('.pug-helper-hotkey')!.textContent).toBe('⌃⌃')
    const hotkeyRow = [...container.querySelectorAll('.pug-table--comparison [role="row"]')].find(row => row.textContent?.startsWith('Hotkey'))!
    expect([...hotkeyRow.children].map(cell => cell.textContent)).toEqual(['Hotkey', '⌃⌃', '⌃⌥Space'])

    act(() => state.hotkeysHandler!({ agentTask: { display: '⌥␣', enabled: true, isDoublePress: false } }))
    expect([...hotkeyRow.children].map(cell => cell.textContent)).toEqual(['Hotkey', '⌥⌥', '⌥Space'])
  })

  it('documents the Command-E collapse shortcut and Command-Return send shortcut', () => {
    act(() => state.initHandler!(config))
    openSection('Window shortcuts')

    expect(container.querySelector('.pug-section-header h1')!.textContent).toBe('Window shortcuts')
    const keycaps = [...container.querySelectorAll('.pug-section kbd')].map(el => el.textContent)
    expect(keycaps).toEqual(['⌘E', '⌘↵'])
    const text = container.textContent ?? ''
    for (const windowName of ['Home', 'Dill', 'Paprika', 'Meeting Assistant', 'Ambient Suggestions', 'Skill Reconciliation', 'setup window']) {
      expect(text).toContain(windowName)
    }
  })

  it('dismisses via the footer Done button', () => {
    act(() => state.initHandler!(config))
    const doneButton = [...container.querySelectorAll('button')].find(el => el.textContent === 'Done')!
    act(() => doneButton.click())

    expect(state.dismissPanel).toHaveBeenCalledOnce()
  })
})
