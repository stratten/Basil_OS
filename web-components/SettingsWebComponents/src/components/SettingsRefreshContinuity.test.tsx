// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, type ReactElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionsPanel } from './ConnectionsPanel'
import { ConnectionRow } from './ConnectionRow'
import { CallLogPanel } from './CallLogPanel'
import { ProviderProfilesPanel } from './ProviderProfilesPanel'
import { TranscriptionHistoryPanel } from './TranscriptionHistoryPanel'
import { PermissionsCommandSecurityPanel } from './PermissionsCommandSecurityPanel'
import { ReasoningApiModelsPanel } from './ReasoningApiModelsPanel'
import { TranscriptionApiModelsPanel } from './TranscriptionApiModelsPanel'
import { ModelsSettingsApp } from '../app/ModelsSettingsApp'
import type { ConnectionsSettingsFields, MCPCallLogEntry, MCPConnection, ProviderProfileSummary } from '../types'

let container: HTMLElement
let root: Root

const CONNECTION: MCPConnection = {
  id: 'conn-1',
  friendlyName: 'GitHub',
  description: null,
  serverUrl: 'https://api.githubcopilot.com/mcp',
  enabled: true,
  registeredAt: '2026-01-01T00:00:00Z',
  lastToolRefreshAt: null,
  lastConnectionCheckAt: null,
  lastConnectionStatus: null,
  lastConnectionStatusMessage: null,
  serverName: null,
  serverInstructions: null,
  authKind: 'github_device',
  tools: [{ name: 'list_issues', description: 'List issues.', isReadOnlyHint: true, policy: 'allow' }],
}

const FIELDS: ConnectionsSettingsFields = {
  starterServers: [],
  connections: [CONNECTION],
  callLogEntries: [],
  isLoading: true,
  isAddingConnection: false,
  isLoadingCallLog: false,
  errorMessage: null,
  statusMessage: null,
  pendingFlowFriendlyName: null,
  githubDeviceFlow: null,
  isPollingGitHubDeviceFlow: false,
  providerProfiles: [],
  isLoadingProviderProfiles: false,
  isMutatingProviderProfiles: false,
  providerProfilesStatusMessage: null,
  providerProfilesErrorMessage: null,
}

const CALL_LOG_ENTRY: MCPCallLogEntry = {
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

const PROFILE: ProviderProfileSummary = {
  id: 'profile-1',
  displayName: 'Codex CLI',
  status: 'enabled',
  capabilityState: 'unverified',
  description: null,
  routingHints: [],
  revision: 1,
  hasObservedCapabilities: false,
  activeWorkspaceGrants: [],
  isStructurallyValid: true,
  validationError: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
}

function renderNode(node: ReactElement) {
  act(() => { root.render(node) })
}

beforeEach(() => {
  const postMessage = vi.fn()
  window.webkit = {
    messageHandlers: {
      basilConnectionsSettingsBridge: { postMessage },
      basilTranscriptionHistoryBridge: { postMessage },
      basilPermissionsCommandSecurityBridge: { postMessage },
      basilReasoningApiModelsBridge: { postMessage },
      basilTranscriptionApiModelsBridge: { postMessage },
      basilModelsSettingsBridge: { postMessage },
      basilCustomModelsBridge: { postMessage },
    },
  }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('Settings refresh continuity', () => {
  it('keeps connections visible and marks the list busy while connections reload', () => {
    renderNode(<ConnectionsPanel fields={FIELDS} pendingId={null} onTrackRequest={vi.fn()} />)
    expect(container.querySelector('.connections-panel-status')).toBeNull()
    expect(container.querySelector('.connections-list')?.getAttribute('aria-busy')).toBe('true')
  })

  it('collapses connection tool policies through a presence region', () => {
    renderNode(<ConnectionRow connection={CONNECTION} pendingId={null} onTrackRequest={vi.fn()} />)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    expect(container.querySelector('.connections-row-tools')?.parentElement?.getAttribute('data-presence-phase')).not.toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    expect(container.querySelector('.connections-row-tools')).toBeNull()
  })

  it('keeps call log entries visible while the call log refreshes', () => {
    renderNode(<CallLogPanel entries={[CALL_LOG_ENTRY]} connections={[CONNECTION]} isLoading pendingId={null} onTrackRequest={vi.fn()} />)
    expect(container.querySelector('.connections-call-log-status-message')).toBeNull()
    expect(container.querySelector('.connections-call-log-list')?.getAttribute('aria-busy')).toBe('true')
  })

  it('keeps provider profiles visible while provider profiles reload', () => {
    renderNode(
      <ProviderProfilesPanel
        providerProfiles={[PROFILE]}
        isLoading
        isMutating={false}
        statusMessage={null}
        errorMessage={null}
        pendingId={null}
        requestError={null}
        onTrackRequest={vi.fn()}
        configEvent={null}
        onConsumeConfigEvent={vi.fn()}
        folderEvent={null}
        onConsumeFolderEvent={vi.fn()}
      />,
    )
    expect(container.textContent).not.toContain('Loading provider profiles...')
    expect(container.querySelector('.connections-list')?.getAttribute('aria-busy')).toBe('true')
  })

  it('keeps transcription history rows visible while history reloads', () => {
    renderNode(<TranscriptionHistoryPanel />)
    act(() => {
      window.basilTranscriptionHistory!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoading: true,
        error: null,
        timeFrameId: 'week',
        searchText: '',
        currentlyPlayingId: null,
        activeRetranscriptionId: null,
        retranscriptionProgressMessage: null,
        retranscriptionProgressFraction: null,
        currentGlobalTranscriptionModelId: 'whisper-1',
        availableRetranscriptionModels: [],
        transcriptions: [{
          id: 'tx-1',
          formattedDate: 'Sep 2, 2026',
          formattedLastTranscribedDate: null,
          formattedDuration: '0:42',
          displayText: 'Hello world',
          modelName: 'whisper-1',
          status: 'completed',
          errorMessage: null,
        }],
        timeFrameOptions: [{ id: 'week', label: '7 Days' }, { id: 'all', label: 'All Time' }],
      })
    })
    expect(container.querySelectorAll('.transcription-history-item')).toHaveLength(1)
    expect(container.querySelector('.transcription-history-list')?.getAttribute('aria-busy')).toBe('true')
  })

  it('keeps command approval settings visible when a later snapshot is loading', () => {
    renderNode(<PermissionsCommandSecurityPanel />)
    const settings = {
      approvalMode: 'whitelist_only' as const,
      showFullCommandInPrompt: true,
      rememberChoiceOption: true,
      autoApproveReadOnly: false,
      blockDangerousPatterns: true,
      whitelistedCount: 0,
      safeExecutionMode: false,
      approvalTimeoutSeconds: 120,
      timeoutBehavior: 'wait_forever' as const,
    }
    act(() => {
      window.basilPermissionsCommandSecurity!.onEvent({ type: 'init', protocolVersion: 1, isLoading: false, error: null, approvalSettings: settings, whitelistPatterns: [] })
    })
    act(() => {
      window.basilPermissionsCommandSecurity!.onEvent({ type: 'init', protocolVersion: 1, isLoading: true, error: null, approvalSettings: settings, whitelistPatterns: [] })
    })
    expect(container.textContent).not.toContain('Loading command approval settings')
    expect(container.textContent).toContain('No whitelisted commands yet')
  })

  it('keeps reasoning API providers visible while they reload', () => {
    renderNode(<ReasoningApiModelsPanel />)
    const providers = [{
      id: 'anthropic', name: 'Anthropic', enabled: true, usingOwnApiKey: true, hasKey: true,
      models: [{ id: 'claude-sonnet', name: 'Claude Sonnet', description: 'fast', capabilities: ['reasoning'], supportsExtendedThinking: true, enabled: false }],
    }]
    act(() => { window.basilReasoningApiModels!.onEvent({ type: 'init', protocolVersion: 1, isLoading: false, useApiModels: true, providers } as any) })
    act(() => { window.basilReasoningApiModels!.onEvent({ type: 'init', protocolVersion: 1, isLoading: true, useApiModels: true, providers } as any) })
    expect(container.querySelector('.reasoning-api-models-status')).toBeNull()
    expect(container.textContent).toContain('Anthropic')
  })

  it('keeps transcription API models visible while they reload', () => {
    renderNode(<TranscriptionApiModelsPanel />)
    const event = {
      type: 'init',
      protocolVersion: 1,
      useApiTranscriptionModels: true,
      openaiEnabled: true,
      openaiHasKey: true,
      models: [{ id: 'openai-whisper-1', displayName: 'Whisper (OpenAI API)', description: 'proven', enabled: true }],
    }
    act(() => { window.basilTranscriptionApiModels!.onEvent({ ...event, isLoading: false } as any) })
    act(() => { window.basilTranscriptionApiModels!.onEvent({ ...event, isLoading: true } as any) })
    expect(container.querySelector('.transcription-api-models-status')).toBeNull()
    expect(container.textContent).toContain('Whisper (OpenAI API)')
  })

  it('keeps local model groups visible while models reload', () => {
    renderNode(<ModelsSettingsApp />)
    const event = {
      type: 'init',
      protocolVersion: 1,
      localVisionFallbackEnabled: false,
      isLocalVisionFallbackModelInstalled: false,
      reasoningGroups: [{
        provider: 'Qwen',
        models: [{ id: 'Qwen-a', modelType: 'Qwen', variantId: 'a', name: 'Qwen A', capabilities: ['reasoning'], size: 4_000_000_000, statusKind: 'downloadable' }],
      }],
      transcriptionGroups: [],
    }
    act(() => { window.basilModelsSettings!.onEvent({ ...event, isLoadingModels: false } as any) })
    act(() => { window.basilModelsSettings!.onEvent({ ...event, isLoadingModels: true } as any) })
    expect(container.querySelector('.models-settings-status')).toBeNull()
    expect(container.textContent).toContain('Qwen A')
  })
})
