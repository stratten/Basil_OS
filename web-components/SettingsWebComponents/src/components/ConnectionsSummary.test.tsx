// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { MCPConnection } from '../types'
import { ConnectionsSummary, connectionSummaryLabels } from './ConnectionsSummary'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

function connection(id: string, status: string | null, friendlyName = id): MCPConnection {
  return {
    id,
    friendlyName,
    description: null,
    serverUrl: 'https://example.test/mcp',
    enabled: true,
    registeredAt: '2026-11-01T00:00:00Z',
    lastToolRefreshAt: null,
    lastConnectionCheckAt: null,
    lastConnectionStatus: status,
    lastConnectionStatusMessage: null,
    serverName: null,
    serverInstructions: null,
    authKind: 'oauth',
    tools: [],
  } as MCPConnection
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

function render(connections: MCPConnection[]) {
  act(() => root.render(<ConnectionsSummary connections={connections} />))
}

describe('ConnectionsSummary', () => {
  it('renders nothing when nothing is connected', () => {
    render([])
    expect(container.innerHTML).toBe('')
  })

  it('names the connections and says everything is healthy', () => {
    render([connection('1', 'healthy', 'Work inbox'), connection('2', 'healthy', 'GitHub')])
    expect(container.textContent).toContain('2 connections set up: Work inbox, GitHub')
    expect(container.textContent).toContain('2 healthy')
    expect(container.querySelector('.connections-summary')?.getAttribute('data-needs-attention')).toBe('false')
  })

  it('uses the singular for one connection and flags one that needs attention', () => {
    render([connection('1', 'needs_reconnect', 'Slack')])
    expect(container.textContent).toContain('1 connection set up: Slack')
    expect(container.textContent).toContain('1 needs attention')
    expect(container.querySelector('.connections-summary')?.getAttribute('data-needs-attention')).toBe('true')
  })

  it('counts healthy, attention and unchecked connections separately, with every error status needing attention', () => {
    render([
      connection('a', 'healthy'),
      connection('b', 'error'),
      connection('c', 'token_unavailable'),
      connection('d', null),
      connection('e', 'something_new'),
    ])
    expect(container.textContent).toContain('1 healthy, 2 need attention, 2 not checked yet')
  })

  it('shows a count when two connections share a name', () => {
    render([connection('1', 'healthy', 'Gmail'), connection('2', 'healthy', 'Gmail'), connection('3', 'healthy', 'GitHub')])
    expect(container.textContent).toContain('3 connections set up: Gmail (2), GitHub')
  })

  it('keeps a very long name inside the summary instead of dropping it', () => {
    const longName = 'A'.repeat(300)
    render([connection('1', 'healthy', longName)])
    expect(container.textContent).toContain(longName)
  })
})

describe('connectionSummaryLabels', () => {
  it('keeps first-seen order and counts repeats', () => {
    expect(connectionSummaryLabels(['Gmail', 'Slack', 'Gmail', 'Gmail'])).toEqual(['Gmail (3)', 'Slack'])
    expect(connectionSummaryLabels([])).toEqual([])
  })
})
