// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { BasilConversation, CHIP_REVEAL_DELAY_MS } from './BasilConversation'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const onUserMessage = vi.fn()
let container: HTMLElement
let root: Root

const chips = [
  { id: 'wordy', label: 'Too wordy', message: 'They are too wordy.', preliminaryStatusMessage: 'Noting that.' },
  { id: 'confirm', label: 'Too many confirmations', message: 'They ask for confirmation too often.', preliminaryStatusMessage: 'Noting that too.' },
  { id: 'wrong', label: 'Get things wrong', message: 'They get things wrong.', preliminaryStatusMessage: 'Noted.' },
]

function render(props: { chipsMultiSelect?: boolean; isStreaming?: boolean; chipSet?: typeof chips }) {
  act(() => {
    root.render(
      <BasilConversation
        messages={[]}
        chips={props.chipSet ?? chips}
        chipsMultiSelect={props.chipsMultiSelect}
        observations={[]}
        pendingProposals={{}}
        isStreaming={props.isStreaming ?? false}
        onUserMessage={onUserMessage}
        onReceiptAction={vi.fn()}
        onAgendaConfirmationResolved={vi.fn()}
      />,
    )
  })
  // Chips appear a beat after the message settles.
  act(() => { vi.advanceTimersByTime(CHIP_REVEAL_DELAY_MS) })
}

function chipButton(label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll<HTMLButtonElement>('.chip-row-buttons button'))
    .find(button => button.textContent?.includes(label))
  if (!found) throw new Error(`No chip button containing "${label}"`)
  return found
}

const sendButton = () => container.querySelector<HTMLButtonElement>('.chip-send-selected')

const otherField = () => container.querySelector<HTMLTextAreaElement>('#chip-other-answer') as HTMLTextAreaElement

function type(field: HTMLTextAreaElement, value: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
    setter?.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function click(element: HTMLElement) {
  act(() => { element.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('BasilConversation multi-select chips', () => {
  it('keeps single-select chips acting immediately with no send button', () => {
    render({})

    click(chipButton('Too wordy'))

    expect(onUserMessage).toHaveBeenCalledWith('They are too wordy.', 'Noting that.')
    expect(sendButton()).toBeNull()
  })

  it('toggles chips without sending and combines every selected answer into one message', () => {
    render({ chipsMultiSelect: true })

    expect(sendButton()?.disabled).toBe(true)
    click(chipButton('Too wordy'))
    click(chipButton('Too many confirmations'))

    expect(onUserMessage).not.toHaveBeenCalled()
    expect(chipButton('Too wordy').getAttribute('aria-pressed')).toBe('true')
    expect(chipButton('Get things wrong').getAttribute('aria-pressed')).toBe('false')
    expect(sendButton()?.textContent).toBe('Send 2 answers')

    click(sendButton() as HTMLButtonElement)

    expect(onUserMessage).toHaveBeenCalledTimes(1)
    expect(onUserMessage).toHaveBeenCalledWith(
      'They are too wordy.\nThey ask for confirmation too often.',
      'Noting that.',
    )
  })

  it('never changes a chip\'s content or layout structure when it is selected', () => {
    render({ chipsMultiSelect: true })
    const before = chipButton('Too wordy').innerHTML

    click(chipButton('Too wordy'))
    const selected = chipButton('Too wordy')

    expect(selected.innerHTML).toBe(before)
    expect(selected.classList.contains('chip-selected')).toBe(true)
    expect(selected.querySelector('.chip-check')?.getAttribute('aria-hidden')).toBe('true')
  })

  it('lets the user deselect a chip and keeps the send button disabled with nothing selected', () => {
    render({ chipsMultiSelect: true })

    click(chipButton('Too wordy'))
    expect(sendButton()?.disabled).toBe(false)
    expect(sendButton()?.textContent).toBe('Send answer')
    click(chipButton('Too wordy'))

    expect(sendButton()?.disabled).toBe(true)
    click(sendButton() as HTMLButtonElement)
    expect(onUserMessage).not.toHaveBeenCalled()
  })

  it('clears the selection when the agent replaces the chips', () => {
    render({ chipsMultiSelect: true })
    click(chipButton('Too wordy'))

    render({
      chipsMultiSelect: true,
      chipSet: [{ id: 'daily', label: 'Email', message: 'Mostly email.', preliminaryStatusMessage: 'Noted.' }],
    })

    expect(chipButton('Email').getAttribute('aria-pressed')).toBe('false')
    expect(sendButton()?.disabled).toBe(true)
  })

  it('sends typed text from the panel field together with the picked chips', () => {
    render({ chipsMultiSelect: true })

    click(chipButton('Too wordy'))
    type(otherField(), '  Also hates jargon.  ')
    expect(sendButton()?.textContent).toBe('Send 2 answers')
    click(sendButton() as HTMLButtonElement)

    expect(onUserMessage).toHaveBeenCalledTimes(1)
    expect(onUserMessage).toHaveBeenCalledWith('They are too wordy.\nAlso hates jargon.', 'Noting that.')
  })

  it('lets the panel field be sent alone and ignores whitespace-only text', () => {
    render({ chipsMultiSelect: true })

    type(otherField(), '   ')
    expect(sendButton()?.disabled).toBe(true)
    type(otherField(), 'Mostly spreadsheets.')
    expect(sendButton()?.disabled).toBe(false)
    expect(sendButton()?.textContent).toBe('Send answer')
    click(sendButton() as HTMLButtonElement)

    expect(onUserMessage).toHaveBeenCalledWith('Mostly spreadsheets.', undefined)
  })

  it('shows the panel field only for multi-select chips and clears it when the chips change', () => {
    render({})
    expect(container.querySelector('#chip-other-answer')).toBeNull()

    render({ chipsMultiSelect: true })
    type(otherField(), 'Leftover text')
    render({
      chipsMultiSelect: true,
      chipSet: [{ id: 'daily', label: 'Email', message: 'Mostly email.', preliminaryStatusMessage: 'Noted.' }],
    })

    expect(otherField().value).toBe('')
  })

  it('shows no chips at all while the agent is still streaming', () => {
    render({ chipsMultiSelect: true, isStreaming: true })

    expect(container.querySelector('.chip-row')).toBeNull()
    expect(sendButton()).toBeNull()
  })
})
