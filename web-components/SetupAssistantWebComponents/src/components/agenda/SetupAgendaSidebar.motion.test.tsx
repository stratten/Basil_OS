// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupSessionAgendaItem } from '@/state/setupAssistantStore'

import { SetupAgendaSidebar } from './SetupAgendaSidebar'

let container: HTMLElement
let root: Root
const overriddenProperties: Array<{ name: string; original: PropertyDescriptor | undefined }> = []

function overrideElementProperty(name: string, descriptor: PropertyDescriptor) {
  overriddenProperties.push({ name, original: Object.getOwnPropertyDescriptor(HTMLElement.prototype, name) })
  Object.defineProperty(HTMLElement.prototype, name, { configurable: true, ...descriptor })
}

function item(id: string, status: SetupSessionAgendaItem['status'] = 'pending'): SetupSessionAgendaItem {
  return { id, title: `Title ${id}`, intent: `Intent ${id}`, kind: 'conversational', source: 'agent', status }
}

function render(items: SetupSessionAgendaItem[], onEntranceChange: (isEntering: boolean) => void, isCollapsed = false) {
  act(() => {
    root.render(
      <SetupAgendaSidebar
        items={items}
        isCollapsed={isCollapsed}
        onToggleCollapsed={() => {}}
        onEntranceChange={onEntranceChange}
      />,
    )
  })
}

function agendaItem(id: string): HTMLElement {
  return container.querySelector(`[data-agenda-item-id="${id}"]`) as HTMLElement
}

function finishEntrance(id: string) {
  const event = new Event('animationend', { bubbles: true })
  Object.defineProperty(event, 'animationName', { value: 'setupEnterRise' })
  act(() => { agendaItem(id).dispatchEvent(event) })
}

function mockRunningEntrances() {
  overrideElementProperty('getAnimations', {
    writable: true,
    value: function getAnimations(this: HTMLElement) {
      return Array.from(this.querySelectorAll('.is-entering')).map(() => ({
        animationName: 'setupEnterRise',
        playState: 'running',
      }))
    },
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  window.matchMedia = vi.fn().mockReturnValue({ matches: false })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  while (overriddenProperties.length > 0) {
    const { name, original } = overriddenProperties.pop() as { name: string; original: PropertyDescriptor | undefined }
    if (original) Object.defineProperty(HTMLElement.prototype, name, original)
    else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name]
  }
})

describe('SetupAgendaSidebar motion', () => {
  it('does not replay the entrance for items present at mount', () => {
    const onEntranceChange = vi.fn()
    render([item('a'), item('b')], onEntranceChange)
    expect(container.querySelectorAll('.is-entering')).toHaveLength(0)
    expect(onEntranceChange).not.toHaveBeenCalledWith(true)
  })

  it('staggers newly proposed items and reports the entrance until each finishes', () => {
    mockRunningEntrances()
    const onEntranceChange = vi.fn()
    render([], onEntranceChange)
    render([item('a'), item('b')], onEntranceChange)

    expect(agendaItem('a').classList.contains('is-entering')).toBe(true)
    expect(agendaItem('a').style.getPropertyValue('--agenda-enter-index')).toBe('0')
    expect(agendaItem('b').style.getPropertyValue('--agenda-enter-index')).toBe('1')
    expect(onEntranceChange).toHaveBeenLastCalledWith(true)

    finishEntrance('a')
    expect(agendaItem('a').classList.contains('is-entering')).toBe(false)
    expect(onEntranceChange).toHaveBeenLastCalledWith(true)

    finishEntrance('b')
    expect(container.querySelectorAll('.is-entering')).toHaveLength(0)
    expect(onEntranceChange).toHaveBeenLastCalledWith(false)
  })

  it('finishes the entrance immediately when no animation runs', () => {
    const onEntranceChange = vi.fn()
    render([], onEntranceChange)
    render([item('a')], onEntranceChange)
    expect(container.querySelectorAll('.is-entering')).toHaveLength(0)
    expect(onEntranceChange).toHaveBeenLastCalledWith(false)
  })

  it('skips the entrance under reduced motion', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true })
    mockRunningEntrances()
    const onEntranceChange = vi.fn()
    render([], onEntranceChange)
    render([item('a')], onEntranceChange)
    expect(container.querySelectorAll('.is-entering')).toHaveLength(0)
    expect(onEntranceChange).not.toHaveBeenCalledWith(true)
  })

  it('clears a pending entrance when the rail collapses', () => {
    mockRunningEntrances()
    const onEntranceChange = vi.fn()
    render([], onEntranceChange)
    render([item('a')], onEntranceChange)
    expect(onEntranceChange).toHaveBeenLastCalledWith(true)
    render([item('a')], onEntranceChange, true)
    expect(onEntranceChange).toHaveBeenLastCalledWith(false)
  })

  it('slides reordered items from their previous position', () => {
    const animate = vi.fn()
    overrideElementProperty('animate', { writable: true, value: animate })
    overrideElementProperty('offsetTop', {
      get(this: HTMLElement) {
        const parent = this.parentElement
        return parent ? Array.from(parent.children).indexOf(this) * 50 : 0
      },
    })
    const onEntranceChange = vi.fn()
    render([item('a'), item('b')], onEntranceChange)
    render([item('a'), item('b', 'in_progress')], onEntranceChange)

    const options = { duration: 320, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' }
    expect(animate).toHaveBeenCalledWith([{ transform: 'translateY(50px)' }, { transform: 'translateY(0)' }], options)
    expect(animate).toHaveBeenCalledWith([{ transform: 'translateY(-50px)' }, { transform: 'translateY(0)' }], options)
  })
})
