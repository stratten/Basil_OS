// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupOrientationObservation } from '@/types'

import { BasilConversation } from './BasilConversation'

let container: HTMLElement
let root: Root

const observations: SetupOrientationObservation[] = [
  { id: 'obs-1', label: 'Email', title: 'Outlook is connected', detail: 'Recent threads are available.', tone: 'email' },
  { id: 'obs-2', label: 'Privacy', title: 'Capture runs every minute', detail: 'Activity capture is on.', tone: 'privacy' },
]

function renderConversation(items: SetupOrientationObservation[] = observations) {
  act(() => {
    root.render(
      <BasilConversation
        messages={[]}
        chips={[]}
        observations={items}
        pendingProposals={{}}
        isStreaming={false}
        onUserMessage={vi.fn()}
        onReceiptAction={vi.fn()}
        onAgendaConfirmationResolved={vi.fn()}
      />,
    )
  })
}

function toggle(): HTMLButtonElement {
  return container.querySelector('.basil-panel-header .conversation-observations-toggle') as HTMLButtonElement
}

function popover(): Element | null {
  return container.querySelector('.conversation-observations-popover')
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('BasilConversation setup notes', () => {
  it('places the notes toggle in the panel header and keeps the notes closed until clicked', () => {
    renderConversation()

    expect(toggle()).not.toBeNull()
    expect(toggle().textContent).toBe('Setup notes (2)')
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
    expect(popover()).toBeNull()
  })

  it('opens the notes as a popover and closes them from the toggle', () => {
    renderConversation()

    act(() => { toggle().click() })
    expect(toggle().getAttribute('aria-expanded')).toBe('true')
    expect(toggle().textContent).toBe('Hide setup notes')
    expect(popover()?.querySelectorAll('.conversation-observation-card')).toHaveLength(2)

    act(() => { toggle().click() })
    expect(popover()).toBeNull()
  })

  it('closes the popover on Escape', () => {
    renderConversation()
    act(() => { toggle().click() })

    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
    expect(popover()).toBeNull()
  })

  it('closes the popover on a pointer press outside it but not inside it', () => {
    renderConversation()
    act(() => { toggle().click() })

    act(() => { popover()!.dispatchEvent(new Event('pointerdown', { bubbles: true })) })
    expect(popover()).not.toBeNull()

    act(() => { document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })) })
    expect(popover()).toBeNull()
  })

  it('renders no notes toggle when there are no observations', () => {
    renderConversation([])

    expect(toggle()).toBeNull()
  })
})
