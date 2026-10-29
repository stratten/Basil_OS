// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import type { SetupConversationMessage } from '@/state/setupAssistantStore'
import { SetupConversationMessageRow } from './SetupConversationMessageRow'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

vi.mock('./AgendaConfirmationCard', () => ({
  AgendaConfirmationCard: () => <section data-testid="quick-check">Quick check</section>,
}))

let container: HTMLElement
let root: Root

function messageWithQuickCheck(overrides: Partial<SetupConversationMessage>): SetupConversationMessage {
  return {
    id: 'message-1',
    role: 'basil',
    content: 'Here is what Dill did with that email.',
    createdAt: '2026-10-26T00:00:00.000Z',
    inlineReceipts: [],
    inlineAgendaConfirmations: [
      { id: 'confirmation-1', agendaItemId: 'intro_dill', prompt: 'Did that make sense?' },
    ],
    ...overrides,
  } as SetupConversationMessage
}

function renderRow(message: SetupConversationMessage) {
  act(() => {
    root.render(
      <SetupConversationMessageRow
        message={message}
        pendingProposals={{}}
        holdReveal={false}
        onReceiptAction={vi.fn()}
        onAgendaConfirmationResolved={vi.fn()}
      />,
    )
  })
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('SetupConversationMessageRow card timing', () => {
  it('keeps the quick check hidden while the message text is still streaming', () => {
    renderRow(messageWithQuickCheck({ streaming: true }))

    expect(container.textContent).toContain('Here is what Dill did')
    expect(container.querySelector('[data-testid="quick-check"]')).toBeNull()
  })

  it('shows the quick check once the message has finished streaming', () => {
    renderRow(messageWithQuickCheck({ streaming: true }))
    renderRow(messageWithQuickCheck({ streaming: false }))

    expect(container.querySelector('[data-testid="quick-check"]')).not.toBeNull()
  })

  it('shows cards on a message that has no text of its own', () => {
    renderRow(messageWithQuickCheck({ content: '', streaming: false }))

    expect(container.querySelector('[data-testid="quick-check"]')).not.toBeNull()
  })
})

describe('SetupConversationMessageRow reveal animation', () => {
  it('fades in the words of a model message that is being revealed', async () => {
    renderRow(messageWithQuickCheck({
      id: 'fading-message',
      revealProgressively: true,
      streaming: true,
      inlineAgendaConfirmations: [],
    }))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 120)) })

    expect(container.querySelector('.basil-message-content.is-revealing')).not.toBeNull()
    expect(container.querySelectorAll('.setup-reveal-word').length).toBeGreaterThan(0)
  })

  it('renders a message that was not revealed progressively as plain text', () => {
    renderRow(messageWithQuickCheck({ id: 'history-message', streaming: false, inlineAgendaConfirmations: [] }))

    expect(container.querySelector('.is-revealing')).toBeNull()
    expect(container.querySelector('.setup-reveal-word')).toBeNull()
    expect(container.textContent).toContain('Here is what Dill did with that email.')
  })

  it('never fades the words of a user message', () => {
    renderRow(messageWithQuickCheck({ id: 'user-message', role: 'user', revealProgressively: true, inlineAgendaConfirmations: [] }))

    expect(container.querySelector('.setup-reveal-word')).toBeNull()
  })
})
