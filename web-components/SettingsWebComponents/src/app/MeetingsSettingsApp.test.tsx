// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MeetingsSettingsApp } from './MeetingsSettingsApp'
import type { MeetingDetectionSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SETTINGS: MeetingDetectionSettingsFields = {
  enabled: true,
  mode: 'prompt',
  pollSeconds: 20,
  excludedBundleIds: ['com.stratten.basil'],
  excludedAppNames: ['Discord'],
  cooldownMinutes: 10,
  useCalendarEnrichment: false,
  requireCalendarMatch: false,
  autoEnd: true,
  inactivityTimeoutMinutes: 2,
}

function sendInit(overrides: Partial<MeetingDetectionSettingsFields> = {}) {
  act(() => {
    window.basilMeetingDetectionSettings!.onEvent({
      type: 'init',
      protocolVersion: 1,
      settings: { ...SETTINGS, ...overrides },
      availableApps: [],
      excludedApps: [{ bundleId: 'com.stratten.basil', name: 'Basil', iconDataUrl: null }],
      requiredBundleIds: ['com.stratten.basil'],
    })
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMeetingDetectionSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<MeetingsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('MeetingsSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.meetings-settings-status')?.textContent).toBe('Loading Meeting Detection settings...')
  })

  it('renders loaded settings, including the mode radio, poll seconds, and excluded app names', () => {
    sendInit()
    expect(container.querySelector<HTMLInputElement>('#meetings-detection-enabled')!.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('input[name="meeting-detection-mode"][value="prompt"]')!.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#meetings-poll-seconds')!.value).toBe('20')
    expect(container.querySelector<HTMLTextAreaElement>('.meetings-exclusions-textarea')!.value).toBe('Discord')
  })

  it('renders the required Basil chip as non-removable', () => {
    sendInit()
    const chips = Array.from(container.querySelectorAll('.app-exclusion-chip'))
    const basilChip = chips.find((chip) => chip.textContent?.includes('Basil'))
    expect(basilChip?.querySelector('.app-exclusion-required')?.textContent).toBe('Required')
    expect(basilChip?.querySelector('.app-exclusion-remove')).toBeNull()
  })

  it('disables the inactivity timeout field when auto-end is off', () => {
    sendInit({ autoEnd: false })
    expect(container.querySelector<HTMLInputElement>('#meetings-inactivity-timeout')!.disabled).toBe(true)
  })

  it('sends requestUpdateEnabled when the toggle changes', () => {
    sendInit()
    act(() => { container.querySelector<HTMLInputElement>('#meetings-detection-enabled')!.click() })
    const call = postMessage.mock.calls.map(([message]) => message).find((message) => message.type === 'requestUpdateEnabled')
    expect(call?.enabled).toBe(false)
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilMeetingDetectionSettings!.onEvent({ type: 'loadError', message: 'Could not load Meeting Detection settings.' }) })
    expect(container.querySelector('.meetings-settings-error p')?.textContent).toBe('Could not load Meeting Detection settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.meetings-settings-error .secondary-button')!.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })
})
