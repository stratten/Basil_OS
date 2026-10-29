// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupConversationMessage } from '@/state/setupAssistantStore'

import { BasilConversation, CHIP_REVEAL_DELAY_MS } from './BasilConversation'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const chips = [{ id: 'dill', label: 'Draft a reply with Dill', message: 'Draft a reply.', preliminaryStatusMessage: 'On it.' }]
const longText = 'Here is a fairly long message that takes a little while to reveal one word at a time on screen.'

let container: HTMLElement
let root: Root
let frameQueue: FrameRequestCallback[] = []
let frameClock = 0

function message(overrides: Partial<SetupConversationMessage> = {}): SetupConversationMessage {
  return {
    id: 'timing-message',
    role: 'basil',
    content: longText,
    createdAt: '2026-10-27T00:00:00.000Z',
    inlineReceipts: [],
    revealProgressively: true,
    streaming: false,
    ...overrides,
  } as SetupConversationMessage
}

function render({ messages, isStreaming = false, pendingProposals = {} }: {
  messages: SetupConversationMessage[]
  isStreaming?: boolean
  pendingProposals?: Record<string, never>
}) {
  act(() => {
    root.render(
      <BasilConversation
        messages={messages}
        chips={chips}
        observations={[]}
        pendingProposals={pendingProposals}
        isStreaming={isStreaming}
        onUserMessage={vi.fn()}
        onReceiptAction={vi.fn()}
        onAgendaConfirmationResolved={vi.fn()}
      />,
    )
  })
}

function runFrames(count: number, frameMs = 16) {
  for (let index = 0; index < count; index += 1) {
    const callbacks = frameQueue
    frameQueue = []
    frameClock += frameMs
    act(() => { callbacks.forEach(callback => callback(frameClock)) })
  }
}

const chipRow = () => container.querySelector('.chip-row')

beforeEach(() => {
  vi.useFakeTimers()
  frameQueue = []
  frameClock = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frameQueue.push(callback)
    return frameQueue.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('BasilConversation suggested next steps timing', () => {
  it('holds the chips back until the message has finished revealing, then adds a beat', () => {
    render({ messages: [message({ id: 'timing-message-a' })] })
    expect(chipRow()).toBeNull()

    runFrames(3)
    act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS * 2) })
    expect(chipRow()).toBeNull()

    runFrames(200)
    expect(chipRow()).toBeNull()

    act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS - 1) })
    expect(chipRow()).toBeNull()

    act(() => { vi.advanceTimersByTime(1) })
    expect(chipRow()).not.toBeNull()
    expect(container.textContent).toContain(longText)
  })

  it('keeps the chips hidden while the turn is still streaming even if the text is fully revealed', () => {
    render({ messages: [message({ id: 'timing-message-b' })], isStreaming: true })
    runFrames(200)
    act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS * 3) })

    expect(chipRow()).toBeNull()

    render({ messages: [message({ id: 'timing-message-b' })], isStreaming: false })
    expect(chipRow()).toBeNull()
    act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS) })
    expect(chipRow()).not.toBeNull()
  })

  it('waits for a message that is still streaming in before showing chips', () => {
    render({ messages: [message({ id: 'timing-message-c', content: 'Short start', streaming: true })] })
    runFrames(100)
    act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS * 3) })
    expect(chipRow()).toBeNull()

    render({ messages: [message({ id: 'timing-message-c', content: 'Short start and the rest.', streaming: false })] })
    runFrames(100)
    expect(chipRow()).toBeNull()
    act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS) })
    expect(chipRow()).not.toBeNull()
  })

  it('shows chips after the delay when the last message needed no reveal', () => {
    render({ messages: [message({ id: 'timing-message-d', revealProgressively: false })] })
    expect(chipRow()).toBeNull()

    act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS) })
    expect(chipRow()).not.toBeNull()
  })
})
