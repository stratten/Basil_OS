// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CaptureSettingsApp } from './CaptureSettingsApp'

let container: HTMLElement
let root: Root

beforeEach(() => {
  window.webkit = {
    messageHandlers: {
      basilActivityCaptureSettingsBridge: { postMessage: vi.fn() },
      basilMemoriesSettingsBridge: { postMessage: vi.fn() },
    },
  }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<CaptureSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function subTab(label: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab'))
    .find((button) => button.textContent === label)!
}

describe('CaptureSettingsApp', () => {
  it('defaults to the Activity Capture sub-tab', () => {
    expect(subTab('Activity Capture').getAttribute('aria-selected')).toBe('true')
    expect(subTab('Memories').getAttribute('aria-selected')).toBe('false')
    expect(container.textContent).toContain('Loading Activity Capture settings...')
  })

  it('switches to the Memories sub-tab and mounts its independent bridge, unmounting Activity Capture', () => {
    act(() => { subTab('Memories').click() })
    expect(subTab('Memories').getAttribute('aria-selected')).toBe('true')
    expect(container.textContent).toContain('Loading Memories settings...')
    expect(container.querySelector('.activity-capture-shell')).toBeNull()
  })

  it('honors an externally requested sub-tab on mount', () => {
    act(() => { root.unmount() })
    container.remove()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => { root.render(<CaptureSettingsApp requestedSubTab="memories" />) })
    expect(subTab('Memories').getAttribute('aria-selected')).toBe('true')
    expect(container.textContent).toContain('Loading Memories settings...')
  })
})
