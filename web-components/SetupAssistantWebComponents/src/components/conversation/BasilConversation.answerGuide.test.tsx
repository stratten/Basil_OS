// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupConversationMessage } from '@/state/setupAssistantStore'
import type { SetupSuggestionChip } from '@/types'

import { ANSWER_GUIDE_EXAMPLES } from './AnswerGuide'
import { BasilConversation } from './BasilConversation'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

function message(id: string, role: 'basil' | 'user', content: string): SetupConversationMessage {
  return { id, role, content, createdAt: '2026-01-01T00:00:00Z', inlineReceipts: [] }
}

function renderConversation(options: { messages: SetupConversationMessage[]; chips?: SetupSuggestionChip[]; isStreaming?: boolean }) {
  act(() => {
    root.render(
      <BasilConversation
        messages={options.messages}
        chips={options.chips ?? []}
        observations={[]}
        pendingProposals={{}}
        isStreaming={options.isStreaming ?? false}
        onUserMessage={vi.fn()}
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

describe('BasilConversation answer guide', () => {
  it('shows guidance and editable examples after Basil asks and before the user has typed', () => {
    renderConversation({ messages: [message('1', 'basil', 'What are you working on?')] })

    expect(container.querySelector('[data-testid="answer-guide"]')).not.toBeNull()
    expect(container.querySelectorAll('.answer-guide-example')).toHaveLength(ANSWER_GUIDE_EXAMPLES.length)
    expect(container.textContent).toContain('A sentence or two is plenty')
  })

  it('puts the chosen example into the composer without sending it, then hides the guide', () => {
    const onUserMessage = vi.fn()
    act(() => {
      root.render(
        <BasilConversation
          messages={[message('1', 'basil', 'What are you working on?')]}
          chips={[]}
          observations={[]}
          pendingProposals={{}}
          isStreaming={false}
          onUserMessage={onUserMessage}
          onReceiptAction={vi.fn()}
          onAgendaConfirmationResolved={vi.fn()}
        />,
      )
    })

    act(() => { container.querySelector<HTMLButtonElement>('.answer-guide-example')!.click() })

    expect(container.querySelector<HTMLTextAreaElement>('.basil-input-row textarea')!.value).toBe(ANSWER_GUIDE_EXAMPLES[0])
    expect(onUserMessage).not.toHaveBeenCalled()
    expect(container.querySelector('[data-testid="answer-guide"]')).toBeNull()
  })

  it('stays hidden before Basil has spoken, while streaming, when chips are offered, and after the user has answered', () => {
    renderConversation({ messages: [] })
    expect(container.querySelector('[data-testid="answer-guide"]')).toBeNull()

    renderConversation({ messages: [message('1', 'basil', 'Hi')], isStreaming: true })
    expect(container.querySelector('[data-testid="answer-guide"]')).toBeNull()

    renderConversation({ messages: [message('1', 'basil', 'Hi')], chips: [{ id: 'a', label: 'Option', message: 'Option' }] })
    expect(container.querySelector('[data-testid="answer-guide"]')).toBeNull()

    renderConversation({ messages: [message('1', 'basil', 'Hi'), message('2', 'user', 'I write briefs')] })
    expect(container.querySelector('[data-testid="answer-guide"]')).toBeNull()
  })
})
