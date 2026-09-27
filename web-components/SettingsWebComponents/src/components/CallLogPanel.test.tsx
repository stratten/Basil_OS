// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CallLogPanel } from './CallLogPanel'
import type { MCPCallLogEntry } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: (id: string) => void

const ENTRY: MCPCallLogEntry = {
  id: 'log-1',
  connectionId: 'conn-1',
  serverUrl: 'https://api.githubcopilot.com/mcp',
  toolName: 'list_issues',
  resultClassification: 'success',
  errorKind: null,
  errorMessage: null,
  contentPreview: 'Returned 4 issues.',
  startedAt: '2026-01-02T00:00:00Z',
  completedAt: '2026-01-02T00:00:01Z',
}

const ERROR_ENTRY: MCPCallLogEntry = {
  ...ENTRY,
  id: 'log-2',
  toolName: 'create_issue',
  resultClassification: 'error',
  errorKind: 'timeout',
  errorMessage: 'The request timed out.',
  contentPreview: null,
}

function render(entries: MCPCallLogEntry[], isLoading = false, pendingId: string | null = null) {
  act(() => { root.render(<CallLogPanel entries={entries} isLoading={isLoading} pendingId={pendingId} onTrackRequest={onTrackRequest} />) })
}

beforeEach(() => {
  postMessage = vi.fn()
  onTrackRequest = vi.fn<(id: string) => void>()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('CallLogPanel', () => {
  it('shows an empty state when there are no entries', () => {
    render([])
    expect(container.querySelector('.connections-call-log-empty')?.textContent).toBe('No external MCP calls have been made yet.')
  })

  it('renders a success entry with its content preview', () => {
    render([ENTRY])
    expect(container.querySelector('.connections-call-log-tool-name')?.textContent).toBe('list_issues')
    expect(container.querySelector('.connections-call-log-preview')?.textContent).toBe('Returned 4 issues.')
    expect(container.querySelector('.connections-call-log-status-success')?.textContent).toBe('Success')
  })

  it('renders an error entry with its error message instead of a preview', () => {
    render([ERROR_ENTRY])
    expect(container.querySelector('.connections-call-log-error-message')?.textContent).toBe('The request timed out.')
    expect(container.querySelector('.connections-call-log-status-error')?.textContent).toBe('timeout')
  })

  it('dispatches requestRefreshCallLog when Refresh is clicked', () => {
    render([ENTRY])
    act(() => { container.querySelector<HTMLButtonElement>('.connections-call-log-header .secondary-button')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestRefreshCallLog' }))
  })

  it('shows a loading status while the call log is refreshing', () => {
    render([], true)
    expect(container.querySelector('.connections-call-log-status-message')?.textContent).toBe('Loading recent activity...')
  })
})
