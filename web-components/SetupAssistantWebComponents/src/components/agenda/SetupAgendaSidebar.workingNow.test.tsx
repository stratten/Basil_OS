// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupSessionAgendaItem } from '@/state/setupAssistantStore'

import { SetupAgendaSidebar, type SetupAgendaSidebarProps } from './SetupAgendaSidebar'
import { agendaPillState, agendaSelectionMessage } from './agendaPillState'

let container: HTMLElement
let root: Root

function item(id: string, status: SetupSessionAgendaItem['status'] = 'pending'): SetupSessionAgendaItem {
  return { id, title: `Title ${id}`, intent: `Intent ${id}`, kind: 'conversational', source: 'agent', status }
}

function render(props: Partial<SetupAgendaSidebarProps> & { items: SetupSessionAgendaItem[] }) {
  act(() => {
    root.render(
      <SetupAgendaSidebar
        isCollapsed={false}
        onToggleCollapsed={() => {}}
        {...props}
      />,
    )
  })
}

const card = (id: string) => container.querySelector<HTMLElement>(`[data-agenda-item-id="${id}"]`)!
const pill = (id: string) => card(id).querySelector('.setup-agenda-sidebar-status-pill')!.textContent
const cardButton = (id: string) => card(id).querySelector<HTMLButtonElement>('.setup-agenda-sidebar-item-button')

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('agenda pill state', () => {
  it('says Working now only while the agent is mid-turn, and Your turn when it is waiting', () => {
    const current = item('a', 'in_progress')

    expect(agendaPillState(current, true)).toBe('working')
    expect(agendaPillState(current, false)).toBe('your_turn')
    expect(agendaPillState(item('b', 'pending'), true)).toBe('pending')
    expect(agendaPillState(item('c', 'completed'), true)).toBe('completed')
  })

  it('words the selection as a message the agent prompt recognizes', () => {
    expect(agendaSelectionMessage(item('a'))).toBe('Let\'s do "Title a" next.')
  })
})

describe('SetupAgendaSidebar working now and selection', () => {
  it('labels the in-progress item Working now while the agent works and Your turn when it waits', () => {
    render({ items: [item('a', 'in_progress'), item('b')], isAgentWorking: true })
    expect(pill('a')).toBe('Working now')
    expect(card('a').classList.contains('is-working')).toBe(true)

    render({ items: [item('a', 'in_progress'), item('b')], isAgentWorking: false })
    expect(pill('a')).toBe('Your turn')
    expect(card('a').classList.contains('is-working')).toBe(false)
  })

  it('asks for an item next when it is clicked', () => {
    const onSelectItem = vi.fn()
    render({ items: [item('a', 'in_progress'), item('b'), item('c', 'skipped')], onSelectItem })

    act(() => { cardButton('b')!.click() })
    act(() => { cardButton('c')!.click() })

    expect(onSelectItem.mock.calls.map(call => (call[0] as SetupSessionAgendaItem).id)).toEqual(['b', 'c'])
  })

  it('does not offer the current or finished items as clickable', () => {
    render({ items: [item('a', 'in_progress'), item('b', 'completed'), item('c')], onSelectItem: vi.fn() })

    expect(cardButton('a')).toBeNull()
    expect(cardButton('b')).toBeNull()
    expect(cardButton('c')).not.toBeNull()
  })

  it('disables the choice while the agent is working so a click cannot interrupt a turn', () => {
    const onSelectItem = vi.fn()
    render({ items: [item('a', 'in_progress'), item('b')], onSelectItem, isAgentWorking: true })

    expect(cardButton('b')!.disabled).toBe(true)
    act(() => { cardButton('b')!.click() })
    expect(onSelectItem).not.toHaveBeenCalled()
  })

  it('is not clickable at all when no handler is given', () => {
    render({ items: [item('a'), item('b')] })

    expect(container.querySelector('.setup-agenda-sidebar-item-button')).toBeNull()
  })

  it('explains the labels and who chooses the order', () => {
    render({ items: [item('a', 'in_progress'), item('b')] })

    const legend = container.querySelector('.setup-agenda-legend')!
    expect(legend.textContent).toContain('Working now')
    expect(legend.textContent).toContain('Your turn')
    expect(legend.textContent).toContain('I choose the order')
    expect(legend.textContent).toContain('click it and I will start it next')
  })

  it('shows progress and what has been saved so far', () => {
    render({ items: [item('a', 'completed'), item('b'), item('c')], savedSoFar: ['Turn on memory after tasks'] })

    expect(container.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('1')
    expect(container.querySelector('[role="progressbar"]')?.getAttribute('aria-valuemax')).toBe('3')
    expect(container.querySelector('.setup-agenda-saved')?.textContent).toContain('Turn on memory after tasks')
  })

  it('shows neither the legend, the progress bar nor a saved list before the agenda exists', () => {
    render({ items: [] })

    expect(container.querySelector('[role="progressbar"]')).toBeNull()
    expect(container.querySelector('.setup-agenda-saved')).toBeNull()
  })
})
