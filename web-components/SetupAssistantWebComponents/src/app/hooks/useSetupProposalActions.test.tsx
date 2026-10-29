// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import {
  MODEL_DOWNLOADS_STARTED_PROMPT,
  SETUP_CHANGE_RESOLVED_PROMPT,
  SETUP_CHANGES_BATCH_RESOLVED_PROMPT,
} from '../setupAssistantPrompts'
import { type SetupProposalActionsApi, useSetupProposalActions } from './useSetupProposalActions'

const proposalApi = vi.hoisted(() => ({
  postProposalDecision: vi.fn(),
  summarizeExecutionResponse: vi.fn(),
}))

vi.mock('../setupAssistantProposalApi', () => proposalApi)

const bridgeRouting = vi.hoisted(() => ({
  executeNativeBridgeToolCall: vi.fn(),
  isNativeBridgeToolCall: vi.fn((toolCall: { tool_name: string }) => toolCall.tool_name === 'start_connection_auth'),
}))

vi.mock('../setupAssistantBridgeRouting', () => bridgeRouting)

function createStore(toolName: string) {
  return {
    state: {
      pendingProposals: {
        'proposal-1': {
          approvalState: 'proposed',
          receipt: {
            id: 'receipt-proposal-1',
            proposal_id: 'proposal-1',
            title: 'Download models',
            rationale: 'Private and offline.',
            approval_state: 'proposed',
            tool_call: {
              id: 'proposal-1',
              tool_name: toolName,
              payload: { model_ids: ['qwen-qwen35-9b-q4km', 'parakeet-v3'] },
              approval_state: 'proposed',
              user_visible_summary: 'Download models',
              privacy_impact: 'none',
              mutates_external_state: false,
              required_permissions: [],
            },
          },
        },
      },
    } as Record<string, unknown>,
    setProposalState: vi.fn(),
    setError: vi.fn(),
    addUserAcknowledgment: vi.fn(),
  }
}

const queuedResponse = {
  results: [
    {
      id: 'a:qwen',
      kind: 'start_model_downloads',
      status: 'applied',
      message: 'qwen is queued.',
      result_payload: { model_id: 'qwen', model_type: 'qwen', download_status: 'queued' },
    },
    {
      id: 'a:parakeet',
      kind: 'start_model_downloads',
      status: 'applied',
      message: 'parakeet is queued.',
      result_payload: { model_id: 'parakeet', model_type: 'parakeet', download_status: 'queued' },
    },
  ],
}

let container: HTMLElement
let root: Root
let actions: SetupProposalActionsApi | null = null

function Harness({ store, startStream }: { store: ReturnType<typeof createStore>; startStream: ReturnType<typeof vi.fn> }) {
  actions = useSetupProposalActions({ store: store as never, startStream: startStream as never })
  return null
}

async function approve(toolName: string, summary: { failed: boolean; message: string }) {
  const store = createStore(toolName)
  const startStream = vi.fn()
  proposalApi.postProposalDecision.mockResolvedValue(queuedResponse)
  proposalApi.summarizeExecutionResponse.mockReturnValue({ ...summary, appearanceChange: null })
  act(() => { root.render(<Harness store={store} startStream={startStream} />) })
  await act(async () => {
    actions!.handleReceiptAction('proposal-1', 'approved')
    await Promise.resolve()
    await Promise.resolve()
  })
  return { store, startStream }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  actions = null
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('useSetupProposalActions model downloads', () => {
  it('hands the conversation back to the setup agent as soon as the downloads are queued', async () => {
    const { store, startStream } = await approve('start_model_downloads', { failed: false, message: 'queued' })

    expect(store.setProposalState).toHaveBeenCalledWith('proposal-1', 'executed', 'queued', null, null)
    expect(startStream).toHaveBeenCalledTimes(1)
    const [prompt, facts, phase, stage, outcomes] = startStream.mock.calls[0]
    expect(prompt).toBe(MODEL_DOWNLOADS_STARTED_PROMPT)
    expect(facts).toBeUndefined()
    expect(phase).toBe('agent_synthesis')
    expect(stage).toBe('conversation')
    expect(outcomes).toEqual([
      {
        kind: 'model_downloads_started',
        proposal_id: 'proposal-1',
        models: [
          { model_id: 'qwen', model_type: 'qwen', download_status: 'queued', message: 'qwen is queued.' },
          { model_id: 'parakeet', model_type: 'parakeet', download_status: 'queued', message: 'parakeet is queued.' },
        ],
      },
    ])
  })

  it('does not restart the agent when the download could not be queued', async () => {
    const { startStream } = await approve('start_model_downloads', { failed: true, message: 'failed' })

    expect(startStream).not.toHaveBeenCalled()
  })

  it('does not use the download prompt for other approvals', async () => {
    const { startStream } = await approve('save_profile_updates', { failed: false, message: 'saved' })

    expect(startStream.mock.calls[0][0]).not.toBe(MODEL_DOWNLOADS_STARTED_PROMPT)
  })
})

describe('useSetupProposalActions applied setup changes', () => {
  it('hands the conversation back to the agent after an approved settings or preferences change', async () => {
    const { store, startStream } = await approve('update_basil_settings', { failed: false, message: 'Read-only auto-approval is on.' })

    expect(store.setProposalState).toHaveBeenCalledWith('proposal-1', 'executed', 'Read-only auto-approval is on.', null, null)
    expect(startStream).toHaveBeenCalledTimes(1)
    const [prompt, facts, phase, stage, outcomes] = startStream.mock.calls[0]
    expect(prompt).toBe(SETUP_CHANGE_RESOLVED_PROMPT)
    expect(facts).toBeUndefined()
    expect(phase).toBe('agent_synthesis')
    expect(stage).toBe('conversation')
    expect(outcomes).toEqual([
      {
        kind: 'setup_change_resolved',
        proposal_id: 'proposal-1',
        tool_name: 'update_basil_settings',
        title: 'Download models',
        status: 'applied',
        message: 'Read-only auto-approval is on.',
        payload: { model_ids: ['qwen-qwen35-9b-q4km', 'parakeet-v3'] },
      },
    ])
  })

  it('tells the agent when the approved change failed so it can recover instead of staying silent', async () => {
    const { store, startStream } = await approve('save_profile_updates', { failed: true, message: 'Could not save.' })

    expect(store.setProposalState).toHaveBeenCalledWith('proposal-1', 'failed', 'Could not save.', 'Could not save.', null)
    expect(startStream).toHaveBeenCalledTimes(1)
    expect(startStream.mock.calls[0][4][0]).toMatchObject({ kind: 'setup_change_resolved', status: 'failed', message: 'Could not save.' })
  })

  it('keeps earlier decisions as context when several receipts are approved in a row', async () => {
    const store = createStore('update_basil_settings')
    const proposals = store.state.pendingProposals as Record<string, Record<string, unknown>>
    const second = { ...proposals['proposal-1'] }
    ;(second.receipt as Record<string, unknown>) = {
      ...(second.receipt as Record<string, unknown>),
      title: 'Save preferences',
      tool_call: { ...((second.receipt as { tool_call: Record<string, unknown> }).tool_call), id: 'proposal-2', tool_name: 'save_profile_updates' },
    }
    proposals['proposal-2'] = second
    const startStream = vi.fn()
    proposalApi.postProposalDecision.mockResolvedValue(queuedResponse)
    proposalApi.summarizeExecutionResponse.mockReturnValue({ failed: false, message: 'ok', appearanceChange: null })
    act(() => { root.render(<Harness store={store} startStream={startStream} />) })

    await act(async () => {
      actions!.handleReceiptAction('proposal-1', 'approved')
      await Promise.resolve()
      await Promise.resolve()
    })
    await act(async () => {
      actions!.handleReceiptAction('proposal-2', 'approved')
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(startStream).toHaveBeenCalledTimes(2)
    const lastOutcomes = startStream.mock.calls[1][4] as Array<Record<string, unknown>>
    expect(lastOutcomes.map(outcome => outcome.proposal_id)).toEqual(['proposal-1', 'proposal-2'])
    expect(lastOutcomes[1].tool_name).toBe('save_profile_updates')
  })

  it('does not restart the agent when the user defers or skips a receipt', async () => {
    const store = createStore('update_basil_settings')
    const startStream = vi.fn()
    proposalApi.postProposalDecision.mockResolvedValue({ results: [] })
    act(() => { root.render(<Harness store={store} startStream={startStream} />) })

    await act(async () => {
      actions!.handleReceiptAction('proposal-1', 'skipped')
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(startStream).not.toHaveBeenCalled()
  })
})

describe('useSetupProposalActions connection sign-in', () => {
  async function approveConnection() {
    const store = createStore('start_connection_auth')
    const startStream = vi.fn()
    act(() => { root.render(<Harness store={store} startStream={startStream} />) })
    await act(async () => {
      actions!.handleReceiptAction('proposal-1', 'approved')
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })
    return { store, startStream }
  }

  it('tells the agent the sign-in page was only opened, so it asks the user to say when they are done', async () => {
    bridgeRouting.executeNativeBridgeToolCall.mockResolvedValue({ requestId: 'r', status: 'executed', message: 'I opened the Slack authorization in your browser.' })

    const { store, startStream } = await approveConnection()

    expect(store.setProposalState).toHaveBeenCalledWith('proposal-1', 'executed', 'I opened the Slack authorization in your browser.')
    expect(startStream).toHaveBeenCalledTimes(1)
    const [prompt, , phase, stage, outcomes] = startStream.mock.calls[0]
    expect(prompt).toBe(SETUP_CHANGE_RESOLVED_PROMPT)
    expect(phase).toBe('agent_synthesis')
    expect(stage).toBe('conversation')
    expect(outcomes[0]).toMatchObject({
      kind: 'setup_change_resolved',
      tool_name: 'start_connection_auth',
      status: 'applied',
      message: 'I opened the Slack authorization in your browser.',
    })
  })

  it('tells the agent why the sign-in could not start so it can explain the manual alternative', async () => {
    bridgeRouting.executeNativeBridgeToolCall.mockRejectedValue(new Error('That server does not support sign-in.'))

    const { store, startStream } = await approveConnection()

    expect(store.setProposalState).toHaveBeenCalledWith('proposal-1', 'failed', 'That action needs attention.', 'That server does not support sign-in.')
    expect(startStream).toHaveBeenCalledTimes(1)
    expect(startStream.mock.calls[0][4][0]).toMatchObject({
      tool_name: 'start_connection_auth',
      status: 'failed',
      message: 'That server does not support sign-in.',
    })
  })

  it('does not restart the agent when other native launches fail', async () => {
    bridgeRouting.isNativeBridgeToolCall.mockImplementation(() => true)
    bridgeRouting.executeNativeBridgeToolCall.mockRejectedValue(new Error('Could not launch.'))
    const store = createStore('launch_agent_task')
    const startStream = vi.fn()
    act(() => { root.render(<Harness store={store} startStream={startStream} />) })

    await act(async () => {
      actions!.handleReceiptAction('proposal-1', 'approved')
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(startStream).not.toHaveBeenCalled()
  })
})

function createBatchStore(states: Record<string, string>) {
  const toolNames: Record<string, string> = { 'proposal-a': 'save_preferences', 'proposal-b': 'start_model_downloads', 'proposal-c': 'save_preferences' }
  const pendingProposals: Record<string, unknown> = {}
  for (const [id, state] of Object.entries(states)) {
    pendingProposals[id] = {
      approvalState: state,
      receipt: {
        id: `receipt-${id}`,
        proposal_id: id,
        title: `Title ${id}`,
        rationale: 'why',
        approval_state: state,
        tool_call: { id, tool_name: toolNames[id], payload: { id }, approval_state: state },
      },
    }
  }
  return {
    state: { pendingProposals } as Record<string, unknown>,
    setProposalState: vi.fn(),
    setError: vi.fn(),
    addUserAcknowledgment: vi.fn(),
  }
}

describe('useSetupProposalActions approve all', () => {
  beforeEach(() => {
    // Earlier suites repoint the native-bridge mock, and clearAllMocks keeps implementations, so restore the default routing.
    bridgeRouting.isNativeBridgeToolCall.mockImplementation(
      (toolCall: { tool_name: string }) => toolCall.tool_name === 'start_connection_auth',
    )
  })

  it('approves the waiting receipts in order and hands the conversation back once with every outcome', async () => {
    const store = createBatchStore({ 'proposal-a': 'proposed', 'proposal-b': 'proposed', 'proposal-c': 'executed' })
    const startStream = vi.fn()
    const order: string[] = []
    proposalApi.postProposalDecision.mockImplementation(async (proposalId: string) => {
      order.push(proposalId)
      return queuedResponse
    })
    proposalApi.summarizeExecutionResponse.mockReturnValue({ failed: false, message: 'done', appearanceChange: null })
    act(() => { root.render(<Harness store={store as never} startStream={startStream} />) })

    await act(async () => {
      actions!.handleApproveAll(['proposal-a', 'proposal-b', 'proposal-c'])
      for (let index = 0; index < 10; index += 1) await Promise.resolve()
    })

    expect(order).toEqual(['proposal-a', 'proposal-b'])
    expect(store.addUserAcknowledgment).toHaveBeenCalledTimes(1)
    expect(store.addUserAcknowledgment.mock.calls[0][0]).toMatchObject({ label: 'Approved all 2.', decision: 'approved' })
    expect(startStream).toHaveBeenCalledTimes(1)
    const [prompt, , phase, stage, outcomes] = startStream.mock.calls[0]
    expect(prompt).toBe(SETUP_CHANGES_BATCH_RESOLVED_PROMPT)
    expect(phase).toBe('agent_synthesis')
    expect(stage).toBe('conversation')
    expect(outcomes).toHaveLength(2)
    expect(outcomes.map((outcome: Record<string, unknown>) => [outcome.proposal_id, outcome.tool_name, outcome.status, outcome.batch])).toEqual([
      ['proposal-a', 'save_preferences', 'applied', true],
      ['proposal-b', 'start_model_downloads', 'applied', true],
    ])
  })

  it('keeps going when one receipt fails and reports it as failed', async () => {
    const store = createBatchStore({ 'proposal-a': 'proposed', 'proposal-c': 'proposed' })
    const startStream = vi.fn()
    proposalApi.postProposalDecision.mockImplementation(async (proposalId: string) => {
      if (proposalId === 'proposal-a') throw new Error('settings write refused')
      return queuedResponse
    })
    proposalApi.summarizeExecutionResponse.mockReturnValue({ failed: false, message: 'done', appearanceChange: null })
    act(() => { root.render(<Harness store={store as never} startStream={startStream} />) })

    await act(async () => {
      actions!.handleApproveAll(['proposal-a', 'proposal-c'])
      for (let index = 0; index < 10; index += 1) await Promise.resolve()
    })

    expect(store.setProposalState).toHaveBeenCalledWith('proposal-a', 'failed', 'That action needs attention.', 'settings write refused')
    expect(startStream).toHaveBeenCalledTimes(1)
    const outcomes = startStream.mock.calls[0][4] as Record<string, unknown>[]
    expect(outcomes.map(outcome => [outcome.proposal_id, outcome.status])).toEqual([
      ['proposal-a', 'failed'],
      ['proposal-c', 'applied'],
    ])
  })

  it('does nothing when no receipt is still waiting', async () => {
    const store = createBatchStore({ 'proposal-a': 'executed', 'proposal-c': 'failed' })
    const startStream = vi.fn()
    act(() => { root.render(<Harness store={store as never} startStream={startStream} />) })

    await act(async () => {
      actions!.handleApproveAll(['proposal-a', 'proposal-c'])
      await Promise.resolve()
    })

    expect(proposalApi.postProposalDecision).not.toHaveBeenCalled()
    expect(store.addUserAcknowledgment).not.toHaveBeenCalled()
    expect(startStream).not.toHaveBeenCalled()
  })
})
