// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MeetingAutomationPanel } from './MeetingAutomationPanel'
import type { MeetingAutomationSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SETTINGS: MeetingAutomationSettingsFields = {
  autoRetranscribeOnStop: false,
  autoRetranscribeDuringRecording: false,
  retranscribeWindowMinutes: 10,
  autoAnalyzeOnComplete: false,
  autoAnalyzeModes: [],
  autoAnalyzeCustomInstructions: '',
  autoAnalyzeTiming: 'after',
}

const MODES = [
  { id: 'action_items', label: 'Action Items' },
  { id: 'summary', label: 'Summary' },
]

function sendInit(overrides: Partial<MeetingAutomationSettingsFields> = {}) {
  act(() => {
    window.basilMeetingAutomationSettings!.onEvent({
      type: 'init',
      protocolVersion: 1,
      settings: { ...SETTINGS, ...overrides },
      analysisModes: MODES,
    })
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMeetingAutomationSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<MeetingAutomationPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('MeetingAutomationPanel', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.meetings-settings-status')?.textContent).toBe('Loading Meeting Automation settings...')
  })

  it('hides the interval field and analysis controls until their gating toggles are on', () => {
    sendInit()
    expect(container.querySelector('#meetings-automation-interval')).toBeNull()
    expect(container.querySelector('#meetings-automation-instructions')).toBeNull()
  })

  it('reveals the interval field when re-transcribe-during-recording is on', () => {
    sendInit({ autoRetranscribeDuringRecording: true, retranscribeWindowMinutes: 15 })
    expect(container.querySelector<HTMLInputElement>('#meetings-automation-interval')!.value).toBe('15')
  })

  it('reveals the modes checklist and custom instructions when auto-analyze is on', () => {
    sendInit({ autoAnalyzeOnComplete: true, autoAnalyzeModes: ['summary'], autoAnalyzeCustomInstructions: 'Focus on blockers.' })
    const checkboxes = container.querySelectorAll<HTMLInputElement>('.meetings-automation-mode-toggle input[type="checkbox"]')
    expect(checkboxes).toHaveLength(2)
    expect(checkboxes[1].checked).toBe(true)
    expect(container.querySelector<HTMLTextAreaElement>('#meetings-automation-instructions')!.value).toBe('Focus on blockers.')
  })

  it('sends a correlated mode toggle request', () => {
    sendInit({ autoAnalyzeOnComplete: true })
    const checkbox = container.querySelectorAll<HTMLInputElement>('.meetings-automation-mode-toggle input[type="checkbox"]')[0]
    act(() => { checkbox.click() })
    const call = postMessage.mock.calls.map(([message]) => message).find((message) => message.type === 'requestUpdateAutoAnalyzeMode')
    expect(call).toMatchObject({ mode: 'action_items', isOn: true })
  })

  it('surfaces an error from a failed update instead of assuming success', () => {
    sendInit()
    act(() => { container.querySelector<HTMLInputElement>('#meetings-automation-retranscribe-on-stop')!.click() })
    const requestId = postMessage.mock.calls.map(([message]) => message).find((message) => message.type === 'requestUpdateAutoRetranscribeOnStop')!.requestId
    act(() => { window.basilMeetingAutomationSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Failed to save.' }) })
    expect(container.querySelector('.meetings-settings-inline-error')?.textContent).toBe('Failed to save.')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilMeetingAutomationSettings!.onEvent({ type: 'loadError', message: 'Could not load Meeting Automation settings.' }) })
    expect(container.querySelector('.meetings-settings-error p')?.textContent).toBe('Could not load Meeting Automation settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.meetings-settings-error .secondary-button')!.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })
})
