// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SettingsSubTabs } from './SettingsSubTabs'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type FixtureTab = 'first' | 'second' | 'third'

const TABS = [
  { id: 'first' as FixtureTab, label: 'First' },
  { id: 'second' as FixtureTab, label: 'Second' },
  { id: 'third' as FixtureTab, label: 'Third' },
]

function renderTabs(selected: FixtureTab, onSelect: (id: FixtureTab) => void) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root: Root = createRoot(container)
  act(() => {
    root.render(
      <SettingsSubTabs
        tabs={TABS}
        selected={selected}
        onSelect={onSelect}
        ariaLabel="Fixture sections"
        getTabId={(id) => `fixture-tab-${id}`}
        getPanelId={(id) => `fixture-panel-${id}`}
      />,
    )
  })
  return { container, root }
}

function tabButton(container: HTMLElement, label: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab')).find((button) => button.textContent === label)!
}

describe('SettingsSubTabs', () => {
  it('marks the selected tab with aria-selected and matching ids and aria-controls from supplied callbacks', () => {
    const { container, root } = renderTabs('first', vi.fn())
    const first = tabButton(container, 'First')
    expect(first.id).toBe('fixture-tab-first')
    expect(first.getAttribute('aria-controls')).toBe('fixture-panel-first')
    expect(first.getAttribute('aria-selected')).toBe('true')
    expect(tabButton(container, 'Second').getAttribute('aria-selected')).toBe('false')
    act(() => { root.unmount() })
    container.remove()
  })

  it('calls onSelect when a tab is clicked', () => {
    const onSelect = vi.fn()
    const { container, root } = renderTabs('first', onSelect)
    act(() => { tabButton(container, 'Second').click() })
    expect(onSelect).toHaveBeenCalledWith('second')
    act(() => { root.unmount() })
    container.remove()
  })

  it('supports ArrowRight, ArrowLeft, Home, and End keyboard navigation', () => {
    const onSelect = vi.fn()
    const { container, root } = renderTabs('first', onSelect)
    act(() => { tabButton(container, 'First').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    expect(onSelect).toHaveBeenLastCalledWith('second')
    act(() => { tabButton(container, 'First').dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })) })
    expect(onSelect).toHaveBeenLastCalledWith('third')
    act(() => { tabButton(container, 'First').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })) })
    expect(onSelect).toHaveBeenLastCalledWith('third')
    act(() => { tabButton(container, 'Third').dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })) })
    expect(onSelect).toHaveBeenLastCalledWith('first')
    act(() => { root.unmount() })
    container.remove()
  })

  it('labels the tablist with the supplied ariaLabel', () => {
    const { container, root } = renderTabs('first', vi.fn())
    expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe('Fixture sections')
    act(() => { root.unmount() })
    container.remove()
  })
})
