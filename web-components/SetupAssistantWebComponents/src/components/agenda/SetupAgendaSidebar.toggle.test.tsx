// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupSessionAgendaItem } from '@/state/setupAssistantStore'

import { SetupAgendaSidebar } from './SetupAgendaSidebar'

let container: HTMLElement
let root: Root

function item(id: string, status: SetupSessionAgendaItem['status'] = 'pending'): SetupSessionAgendaItem {
  return { id, title: `Title ${id}`, intent: `Intent ${id}`, kind: 'conversational', source: 'agent', status }
}

function render(isCollapsed: boolean, onToggleCollapsed: (collapsed: boolean) => void, onSelectItem?: (item: SetupSessionAgendaItem) => void) {
  act(() => {
    root.render(
      <SetupAgendaSidebar
        items={[item('a'), item('b', 'completed')]}
        isCollapsed={isCollapsed}
        onToggleCollapsed={onToggleCollapsed}
        onSelectItem={onSelectItem}
      />,
    )
  })
}

function click(element: Element) {
  act(() => { element.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
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
  window.getSelection()?.removeAllRanges()
  vi.restoreAllMocks()
})

describe('SetupAgendaSidebar open and close', () => {
  it('puts the button first in the sidebar in both shapes, so it does not move from the top to the bottom', () => {
    render(false, () => {})
    const expandedButton = container.querySelector('button[aria-label="Collapse agenda"]') as HTMLElement
    expect(expandedButton.closest('header')).not.toBeNull()
    expect(container.querySelector('aside')?.firstElementChild).toBe(container.querySelector('header'))

    render(true, () => {})
    const collapsedButton = container.querySelector('button[aria-label="Expand agenda"]') as HTMLElement
    expect(container.querySelector('aside')?.firstElementChild).toBe(collapsedButton)
    expect(collapsedButton.className).toBe(expandedButton.className)
  })

  it('opens when the collapsed rail is clicked anywhere, including its ring and dots', () => {
    const onToggle = vi.fn()
    render(true, onToggle)

    click(container.querySelector('.setup-agenda-collapsed-ring') as Element)
    click(container.querySelector('aside') as Element)

    expect(onToggle).toHaveBeenCalledTimes(2)
    expect(onToggle).toHaveBeenNthCalledWith(1, false)
  })

  it('opens once, not twice, when the button itself is clicked', () => {
    const onToggle = vi.fn()
    render(true, onToggle)

    click(container.querySelector('button[aria-label="Expand agenda"]') as Element)

    expect(onToggle).toHaveBeenCalledTimes(1)
    expect(onToggle).toHaveBeenCalledWith(false)
  })

  it('closes when the open sidebar is clicked on its title or on text that does nothing', () => {
    const onToggle = vi.fn()
    render(false, onToggle)

    click(container.querySelector('.setup-agenda-sidebar-title') as Element)
    click(container.querySelector('[data-agenda-item-id="b"] .setup-agenda-sidebar-item-intent') as Element)

    expect(onToggle).toHaveBeenCalledTimes(2)
    expect(onToggle).toHaveBeenCalledWith(true)
  })

  it('closes once, not twice, when the button itself is clicked', () => {
    const onToggle = vi.fn()
    render(false, onToggle)

    click(container.querySelector('button[aria-label="Collapse agenda"]') as Element)

    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('does not close when someone picks an item or opens the legend', () => {
    const onToggle = vi.fn()
    const onSelect = vi.fn()
    render(false, onToggle, onSelect)

    click(container.querySelector('.setup-agenda-sidebar-item-button') as Element)
    const summary = container.querySelector('summary')
    if (summary) click(summary)

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onToggle).not.toHaveBeenCalled()
  })

  it('does not close while text in the sidebar is selected', () => {
    const onToggle = vi.fn()
    render(false, onToggle)
    const title = container.querySelector('.setup-agenda-sidebar-title') as HTMLElement
    const range = document.createRange()
    range.selectNodeContents(title)
    window.getSelection()?.removeAllRanges()
    window.getSelection()?.addRange(range)

    click(title)

    expect(onToggle).not.toHaveBeenCalled()
  })
})
