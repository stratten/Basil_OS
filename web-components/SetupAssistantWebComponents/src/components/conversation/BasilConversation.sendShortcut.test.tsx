// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { BasilConversation } from './BasilConversation'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const onUserMessage = vi.fn()
let container: HTMLElement
let root: Root

function typeIntoComposer(text: string): HTMLTextAreaElement {
  const textarea = container.querySelector('textarea') as HTMLTextAreaElement
  const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
  act(() => {
    setValue.call(textarea, text)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
  return textarea
}

function pressEnter(textarea: HTMLTextAreaElement, modifiers: { metaKey?: boolean; ctrlKey?: boolean }) {
  const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...modifiers })
  act(() => { textarea.dispatchEvent(event) })
  return event
}

beforeEach(() => {
  vi.clearAllMocks()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => {
    root.render(
      <BasilConversation
        messages={[]}
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
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('BasilConversation send shortcut', () => {
  it('sends the draft on Command+Enter and clears the composer', () => {
    const textarea = typeIntoComposer('Have Dill draft a reply')

    const event = pressEnter(textarea, { metaKey: true })

    expect(onUserMessage).toHaveBeenCalledWith('Have Dill draft a reply')
    expect(event.defaultPrevented).toBe(true)
    expect(textarea.value).toBe('')
  })

  it('sends on Control+Enter as well', () => {
    const textarea = typeIntoComposer('Hello')

    pressEnter(textarea, { ctrlKey: true })

    expect(onUserMessage).toHaveBeenCalledWith('Hello')
  })

  it('leaves plain Enter alone so it still adds a new line', () => {
    const textarea = typeIntoComposer('Hello')

    const event = pressEnter(textarea, {})

    expect(onUserMessage).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
  })

  it('does not send an empty draft on Command+Enter', () => {
    const textarea = typeIntoComposer('   ')

    pressEnter(textarea, { metaKey: true })

    expect(onUserMessage).not.toHaveBeenCalled()
  })
})
