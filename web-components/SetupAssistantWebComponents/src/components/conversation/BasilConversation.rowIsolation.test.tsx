// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, memo, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import type { SetupConversationMessage } from '@/state/setupAssistantStore'
import { BasilConversation } from './BasilConversation'

const renderCounts = vi.hoisted(() => new Map<string, number>())

vi.mock('./SetupConversationMessageRow', () => ({
  SetupConversationMessageRow: memo(({ message }: { message: SetupConversationMessage }) => {
    renderCounts.set(message.id, (renderCounts.get(message.id) ?? 0) + 1)
    return <article>{message.content}</article>
  }),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const emptyProposals = {}
const onUserMessage = vi.fn()
const onReceiptAction = vi.fn()
const onAgendaConfirmationResolved = vi.fn()
let updateMiddleMessage: (() => void) | undefined
let updateWorkingLabel: (() => void) | undefined
let container: HTMLElement
let root: Root

function message(id: string, content: string): SetupConversationMessage {
  return {
    id,
    role: 'basil',
    content,
    createdAt: '2026-08-23T00:00:00.000Z',
    inlineReceipts: [],
  }
}

function Harness() {
  const [messages, setMessages] = useState(() => [
    message('first', 'First'),
    message('middle', 'Middle'),
    message('third', 'Third'),
  ])
  const [workingPrimaryLabel, setWorkingPrimaryLabel] = useState<string | null>(null)

  updateMiddleMessage = () => {
    setMessages(current => current.map(item => (
      item.id === 'middle' ? { ...item, content: 'Updated middle' } : item
    )))
  }
  updateWorkingLabel = () => setWorkingPrimaryLabel('Checking the next setup step')

  return (
    <BasilConversation
      messages={messages}
      chips={[]}
      observations={[]}
      pendingProposals={emptyProposals}
      isStreaming={false}
      workingPrimaryLabel={workingPrimaryLabel}
      onUserMessage={onUserMessage}
      onReceiptAction={onReceiptAction}
      onAgendaConfirmationResolved={onAgendaConfirmationResolved}
    />
  )
}

beforeEach(() => {
  renderCounts.clear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => {
    root.render(<Harness />)
  })
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  container.remove()
  updateMiddleMessage = undefined
  updateWorkingLabel = undefined
})

describe('BasilConversation row isolation', () => {
  it('re-renders only the changed message row for a delta or narration update', () => {
    expect(renderCounts).toEqual(new Map([
      ['first', 1],
      ['middle', 1],
      ['third', 1],
    ]))

    act(() => {
      updateMiddleMessage!()
    })
    expect(renderCounts).toEqual(new Map([
      ['first', 1],
      ['middle', 2],
      ['third', 1],
    ]))

    act(() => {
      updateWorkingLabel!()
    })
    expect(renderCounts).toEqual(new Map([
      ['first', 1],
      ['middle', 2],
      ['third', 1],
    ]))
  })
})
