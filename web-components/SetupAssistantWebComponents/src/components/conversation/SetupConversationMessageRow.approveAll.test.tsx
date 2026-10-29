// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import type { SetupConversationMessage } from '@/state/setupAssistantStore'
import { SetupConversationMessageRow } from './SetupConversationMessageRow'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

function receipt(id: string, title: string) {
  return {
    id: `receipt-${id}`,
    proposal_id: id,
    title,
    rationale: `Why ${title}.`,
    approval_state: 'proposed',
    tool_call: {
      id,
      tool_name: 'save_preferences',
      payload: {},
      approval_state: 'proposed',
      user_visible_summary: title,
      privacy_impact: 'none',
      mutates_external_state: false,
      required_permissions: [],
    },
  }
}

function messageWithReceipts(count: number): SetupConversationMessage {
  return {
    id: 'message-1',
    role: 'basil',
    content: 'Two changes are ready.',
    createdAt: '2026-10-27T00:00:00.000Z',
    inlineReceipts: Array.from({ length: count }, (_, index) => receipt(`p${index + 1}`, `Change ${index + 1}`)),
  } as unknown as SetupConversationMessage
}

function renderRow(
  message: SetupConversationMessage,
  options: { pendingProposals?: Record<string, unknown>; onApproveAll?: (ids: string[]) => void } = {},
) {
  act(() => {
    root.render(
      <SetupConversationMessageRow
        message={message}
        pendingProposals={(options.pendingProposals ?? {}) as never}
        holdReveal={false}
        onReceiptAction={vi.fn()}
        onApproveAll={options.onApproveAll}
        onAgendaConfirmationResolved={vi.fn()}
      />,
    )
  })
}

// React listens under the unprefixed or the webkit-prefixed name depending on what the DOM implementation supports, so both are fired.
function dispatchAnimationEnd(element: Element) {
  element.dispatchEvent(new Event('animationend', { bubbles: true }))
  element.dispatchEvent(new Event('webkitAnimationEnd', { bubbles: true }))
}

function buttonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll('button')).find(button => button.textContent === text)
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

describe('Approve all for waiting receipts', () => {
  it('offers one button that approves every waiting receipt in the message', () => {
    const onApproveAll = vi.fn()
    renderRow(messageWithReceipts(2), { onApproveAll })

    expect(container.textContent).toContain('2 changes are waiting for your approval')
    const button = buttonByText('Approve all 2')
    expect(button).toBeDefined()
    act(() => { button!.click() })

    expect(onApproveAll).toHaveBeenCalledTimes(1)
    expect(onApproveAll).toHaveBeenCalledWith(['p1', 'p2'])
  })

  it('does not offer it for a single receipt', () => {
    renderRow(messageWithReceipts(1), { onApproveAll: vi.fn() })

    expect(container.querySelector('.receipt-batch-bar')).toBeNull()
  })

  it('does not offer it when no handler is provided', () => {
    renderRow(messageWithReceipts(2))

    expect(container.querySelector('.receipt-batch-bar')).toBeNull()
  })

  it('counts only the receipts that are still waiting and folds away when fewer than two remain', () => {
    const onApproveAll = vi.fn()
    const message = messageWithReceipts(3)
    renderRow(message, {
      onApproveAll,
      pendingProposals: { p1: { approvalState: 'executed', receipt: message.inlineReceipts[0] } },
    })

    expect(buttonByText('Approve all 2')).toBeDefined()
    act(() => { buttonByText('Approve all 2')!.click() })
    expect(onApproveAll).toHaveBeenCalledWith(['p2', 'p3'])

    renderRow(message, {
      onApproveAll,
      pendingProposals: {
        p1: { approvalState: 'executed', receipt: message.inlineReceipts[0] },
        p2: { approvalState: 'executed', receipt: message.inlineReceipts[1] },
      },
    })
    const bar = container.querySelector('.setup-card-reveal.is-collapsed')
    expect(bar).not.toBeNull()
    expect(bar!.getAttribute('aria-hidden')).toBe('true')
    expect((bar!.querySelector('.receipt-batch-bar-button') as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('Receipt cards reveal', () => {
  it('wraps each receipt so it fades in and opens its space smoothly, then lifts the clip', () => {
    renderRow(messageWithReceipts(1))

    const reveal = container.querySelector('.setup-card-reveal') as HTMLElement
    expect(reveal).not.toBeNull()
    expect(reveal.querySelector('.consent-receipt')).not.toBeNull()
    expect(reveal.classList.contains('is-settled')).toBe(false)

    act(() => {
      dispatchAnimationEnd(reveal)
    })
    expect(reveal.classList.contains('is-settled')).toBe(true)
  })

  it('ignores animations that finish inside the card', () => {
    renderRow(messageWithReceipts(1))

    const reveal = container.querySelector('.setup-card-reveal') as HTMLElement
    act(() => {
      dispatchAnimationEnd(reveal.querySelector('.consent-receipt')!)
    })
    expect(reveal.classList.contains('is-settled')).toBe(false)
  })
})
