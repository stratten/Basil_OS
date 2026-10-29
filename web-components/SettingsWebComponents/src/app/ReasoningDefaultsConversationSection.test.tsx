// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { fireEvent } from '@testing-library/react'
import { createRoot, type Root } from 'react-dom/client'
import { ReasoningDefaultsSettingsApp } from './ReasoningDefaultsSettingsApp'
import type { ReasoningDefaultsSettingsSnapshot } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SETTINGS: ReasoningDefaultsSettingsSnapshot = {
  localModels: [{ id: 'local-1', name: 'local-1', displayName: 'Local One', provider: 'ollama', isApiModel: false }],
  apiModels: [],
  customModels: [],
  selectedModelId: 'local-1',
  useApiModels: false,
  closeAssistantSessionOnInsert: false,
  assistantOutputPasteMode: 'always',
  useRegionSelection: false,
  agentTaskDefaultModality: 'voice',
  agentTaskAutoReopenOnCompletion: true,
  agentTaskPushToTalk: false,
  agentTaskPushToTalkThreshold: 750,
  assistantSessionDefaultModality: 'speak',
  assistantSessionPushToTalk: true,
  assistantSessionPushToTalkThreshold: 900,
}

function sendEvent(type: 'init' | 'snapshot', overrides: Partial<ReasoningDefaultsSettingsSnapshot> = {}) {
  const settings = { ...SETTINGS, ...overrides }
  act(() => {
    window.basilReasoningDefaultsSettings!.onEvent(
      type === 'init'
        ? { type: 'init', protocolVersion: 1, isLoading: false, settings }
        : { type: 'snapshot', isLoading: false, settings },
    )
  })
}

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

function conversationSwitch(): HTMLInputElement {
  return container.querySelector<HTMLInputElement>('#reasoning-defaults-conversation-only-default')!
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilReasoningDefaultsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ReasoningDefaultsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ReasoningDefaultsSettingsApp Conversation section', () => {
  it('treats a missing Conversation only default as off', () => {
    sendEvent('init')
    expect(conversationSwitch().checked).toBe(false)
  })

  it('renders the stored Conversation only default', () => {
    sendEvent('init', { conversationDefaultConversationOnly: true })
    expect(conversationSwitch().checked).toBe(true)
  })

  it('sends a correlated update and reconciles to the native snapshot', () => {
    sendEvent('init', { conversationDefaultConversationOnly: false })
    act(() => { fireEvent.click(conversationSwitch()) })
    const message = lastMessageOfType('requestUpdateConversationDefaultConversationOnly')
    expect(message).toMatchObject({ type: 'requestUpdateConversationDefaultConversationOnly', enabled: true })
    expect(typeof message.requestId).toBe('string')
    expect(conversationSwitch().checked).toBe(true)
    expect(conversationSwitch().disabled).toBe(false)

    act(() => {
      window.basilReasoningDefaultsSettings!.onEvent({ type: 'intentResult', requestId: message.requestId, status: 'error', message: 'Failed to update the Conversation only default.' })
    })
    sendEvent('snapshot', { conversationDefaultConversationOnly: false })
    expect(conversationSwitch().checked).toBe(false)
    expect(conversationSwitch().disabled).toBe(false)
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to update the Conversation only default.')
  })

  it('groups AssistantSession input and behavior controls into one two-column card', () => {
    sendEvent('init')
    const heading = container.querySelector('#reasoning-defaults-assistant-session-heading')!
    const card = heading.closest('section')!
    const columns = card.querySelectorAll('.reasoning-defaults-columns > .reasoning-defaults-column')
    expect(columns).toHaveLength(2)
    expect(columns[0].querySelector('h3')?.textContent).toBe('Input')
    expect(columns[1].querySelector('h3')?.textContent).toBe('Behavior')
    expect(columns[0].getAttribute('role')).toBe('group')
    expect(columns[0].querySelector('#reasoning-defaults-assistant-session-ptt')).not.toBeNull()
    expect(columns[0].querySelector('#assistant-session-threshold-input')).not.toBeNull()
    expect(columns[1].querySelector('#reasoning-defaults-close-on-insert')).not.toBeNull()
    expect(columns[1].querySelector('input[name="assistant-output-paste-mode"]')).not.toBeNull()
    expect(columns[1].querySelector('#reasoning-defaults-region-selection')).not.toBeNull()
    expect(container.querySelectorAll('h2')).toHaveLength(4)
  })
})
