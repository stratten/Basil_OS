// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { PermissionsApplicationPanel } from './PermissionsApplicationPanel'
import type { PermissionsApplicationStatusMap } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function snapshotEvent(overrides: Partial<PermissionsApplicationStatusMap> = {}) {
  return {
    type: 'snapshot' as const,
    permissions: {
      microphone: 'not_determined' as const,
      accessibility: 'denied' as const,
      inputMonitoring: 'unknown' as const,
      screenRecording: 'not_determined' as const,
      appleEvents: 'not_determined' as const,
      ...overrides,
    },
  }
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilPermissionsApplicationBridge: { postMessage } } }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<PermissionsApplicationPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('PermissionsApplicationPanel', () => {
  it('notifies ready and requests the initial permission status on mount', () => {
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestPermissionStatus' }))
  })

  it('renders the established five-permission card set with status icons', () => {
    act(() => { window.basilPermissionsApplication!.onEvent(snapshotEvent()) })
    expect(container.textContent).toContain('Microphone Access')
    expect(container.textContent).toContain('Accessibility')
    expect(container.textContent).toContain('Input Monitoring')
    expect(container.textContent).toContain('Apple Events')
    expect(container.textContent).toContain('Screen Recording')
    expect(container.textContent).toContain('Denied')
    expect(container.querySelectorAll('.permission-icon svg')).toHaveLength(5)
  })

  it('sends requestPermission with the row kind when its action is clicked', () => {
    act(() => { window.basilPermissionsApplication!.onEvent(snapshotEvent()) })
    const button = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Request Permission')!
    act(() => { button.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestPermission', kind: 'microphone' }))
  })

  it('sends openSystemSettings with the row kind when Open Settings is clicked', () => {
    act(() => { window.basilPermissionsApplication!.onEvent(snapshotEvent()) })
    const buttons = Array.from(container.querySelectorAll('button')).filter((el) => el.textContent === 'Open System Settings')
    act(() => { buttons[0].click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'openSystemSettings', kind: 'microphone' }))
  })

  it('hides the request button once every permission is granted', () => {
    act(() => {
      window.basilPermissionsApplication!.onEvent(
        snapshotEvent({ microphone: 'granted', accessibility: 'granted', inputMonitoring: 'granted', appleEvents: 'granted', screenRecording: 'granted' }),
      )
    })
    const requestButtons = Array.from(container.querySelectorAll('button')).filter((el) => el.textContent === 'Request Permission' || el.textContent === 'Request Again')
    expect(requestButtons).toHaveLength(0)
  })
})
