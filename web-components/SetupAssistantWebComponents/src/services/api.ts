import type {
  SetupAction,
  SetupActionExecutionResponse,
  SetupActionSequenceValidationResponse,
  SetupAgentContractResponse,
  SetupAgentModelAccessOptionsResponse,
  SetupAgentModelAccessSelectRequest,
  SetupAgentModelAccessSelectResponse,
  SetupAgentRequest,
  SetupAgentResponse,
  SetupAgentValidationResponse,
  SetupAssistantCompletionRequest,
  SetupDiscoveryResponse,
  SetupModelDownloadStatusResponse,
  SetupToolCall,
  SetupToolCallValidationResponse,
  SetupAgentOutput,
  SetupWrapUpProposal,
} from '@/types'
import type { FontConfig, ThemeConfig } from '@/theme/themeBootstrap'

export type SetupAssistantSkipRequest = SetupAssistantCompletionRequest

declare global {
  interface Window {
    basilSetupAssistantConfig?: {
      apiBaseUrl?: string
      theme?: ThemeConfig
      fonts?: FontConfig
    }
  }
}

const API_BASE = window.basilSetupAssistantConfig?.apiBaseUrl ?? ''
const SETUP_SERVICE_UNAVAILABLE_MESSAGE = 'Basil could not reach the setup service. Please try again once setup services are running.'
const SETUP_SERVICE_INVALID_RESPONSE_MESSAGE = 'Basil could not read the setup service response. Please try again.'

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const responseText = await response.text()
  if (!responseText.trim()) {
    throw new Error(SETUP_SERVICE_INVALID_RESPONSE_MESSAGE)
  }

  try {
    return JSON.parse(responseText) as T
  } catch (error) {
    console.warn('[SetupAssistant] Failed to parse setup service response:', error)
    throw new Error(SETUP_SERVICE_INVALID_RESPONSE_MESSAGE)
  }
}

async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const text = await response.text()
    if (!text.trim()) return SETUP_SERVICE_UNAVAILABLE_MESSAGE
    const parsed = JSON.parse(text) as { detail?: unknown }
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
      return parsed.detail
    }
  } catch {
    // fall through to the generic message below
  }
  return SETUP_SERVICE_UNAVAILABLE_MESSAGE
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(await extractErrorDetail(response))
  }
  return parseJsonResponse<T>(response)
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(await extractErrorDetail(response))
  }
  return parseJsonResponse<T>(response)
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(await extractErrorDetail(response))
  }
  return parseJsonResponse<T>(response)
}

export interface MemoryIntelligenceSettingsUpdate {
  memory_after_task_enabled?: boolean | null
  memory_daily_enabled?: boolean | null
  memory_daily_time_local?: string | null
  memory_processing_model?: string | null
  skill_after_task_enabled?: boolean | null
  skill_daily_enabled?: boolean | null
  skill_daily_time_local?: string | null
  skill_processing_model?: string | null
}

export interface MemoryIntelligenceSettingsSnapshot {
  memory_after_task_enabled: boolean
  skill_after_task_enabled: boolean
}

interface MemoryIntelligenceSettingsResponse {
  settings: MemoryIntelligenceSettingsSnapshot
}

export async function fetchMemoryIntelligenceSettings(): Promise<MemoryIntelligenceSettingsSnapshot> {
  const response = await getJson<MemoryIntelligenceSettingsResponse>('/settings/memory-intelligence')
  return response.settings
}

export async function updateMemoryIntelligenceSettings(
  update: MemoryIntelligenceSettingsUpdate,
): Promise<Record<string, unknown>> {
  return putJson<Record<string, unknown>>('/settings/memory-intelligence', update)
}

export async function fetchSetupAgentContract(): Promise<SetupAgentContractResponse> {
  return getJson<SetupAgentContractResponse>('/setup-assistant/agent-contract')
}

export async function fetchModelAccessOptions(): Promise<SetupAgentModelAccessOptionsResponse> {
  return getJson<SetupAgentModelAccessOptionsResponse>('/setup-assistant/model-access/options')
}

export async function selectModelAccess(
  request: SetupAgentModelAccessSelectRequest,
): Promise<SetupAgentModelAccessSelectResponse> {
  return postJson<SetupAgentModelAccessSelectResponse>('/setup-assistant/model-access/select', request)
}

export interface ProviderApiKeyTestResult {
  provider: string
  valid: boolean
  error?: string | null
}

export async function testProviderApiKey(
  provider: string,
  key: string,
): Promise<ProviderApiKeyTestResult> {
  return postJson<ProviderApiKeyTestResult>('/settings/api_models/api_keys/test', { provider, key })
}

export async function fetchLowRiskDiscovery(): Promise<SetupDiscoveryResponse> {
  return getJson<SetupDiscoveryResponse>('/setup-assistant/discovery/low-risk')
}

export async function fetchModelCatalogDiscovery(): Promise<SetupDiscoveryResponse> {
  return getJson<SetupDiscoveryResponse>('/setup-assistant/discovery/models/catalog')
}

export async function fetchEmailClientDiscovery(): Promise<SetupDiscoveryResponse> {
  return getJson<SetupDiscoveryResponse>('/setup-assistant/discovery/email-clients')
}

export async function fetchConnectionCatalogDiscovery(): Promise<SetupDiscoveryResponse> {
  return getJson<SetupDiscoveryResponse>('/setup-assistant/discovery/connections/catalog')
}

export async function fetchSentEmailMetadataDiscovery(): Promise<SetupDiscoveryResponse> {
  return postJson<SetupDiscoveryResponse>('/setup-assistant/discovery/writing-samples/sent-email-metadata', {
    days_back: 14,
    limit: 25,
  })
}

export async function respondWithSetupAgent(
  request: SetupAgentRequest,
): Promise<SetupAgentResponse> {
  return postJson<SetupAgentResponse>('/setup-assistant/agent/respond', request)
}

export async function validateSetupAgentOutput(
  output: SetupAgentOutput,
  discoveryFacts: SetupDiscoveryResponse['facts'],
): Promise<SetupAgentValidationResponse> {
  return postJson<SetupAgentValidationResponse>('/setup-assistant/validate-agent-output', {
    output,
    discovery_facts: discoveryFacts,
  })
}

export async function validateSetupActionSequence(
  actions: SetupAction[],
): Promise<SetupActionSequenceValidationResponse> {
  return postJson<SetupActionSequenceValidationResponse>('/setup-assistant/actions/sequence/validate', {
    actions,
  })
}

export async function validateSetupToolCalls(
  toolCalls: SetupToolCall[],
): Promise<SetupToolCallValidationResponse> {
  return postJson<SetupToolCallValidationResponse>('/setup-assistant/actions/tool-calls/validate', {
    tool_calls: toolCalls,
  })
}

export async function executeSetupActions(
  actions: SetupAction[],
  toolCalls: SetupToolCall[],
): Promise<SetupActionExecutionResponse> {
  return postJson<SetupActionExecutionResponse>('/setup-assistant/actions/execute', {
    actions,
    tool_calls: toolCalls,
  })
}

export async function applySetupProfileSuggestions(
  approvedFields: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>('/setup-assistant/actions/profile/apply', {
    approved_fields: approvedFields,
  })
}

export async function applySetupWritingSample(
  sample: {
    content: string
    context_type?: string
    recipient?: string | null
    metadata?: Record<string, unknown>
  },
): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>('/setup-assistant/actions/writing-samples/apply', sample)
}

export async function completeSetupAssistant(
  completion: SetupAssistantCompletionRequest,
): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>('/setup-assistant/state/complete', completion)
}

export async function skipSetupAssistant(
  payload: SetupAssistantSkipRequest,
): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>('/setup-assistant/state/skip', payload)
}

export async function dismissSetupReminder(): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>('/setup-assistant/state/dismiss-reminder', {})
}

export async function finalizeSetupAssistant(
  request: SetupAgentRequest,
): Promise<SetupWrapUpProposal> {
  return postJson<SetupWrapUpProposal>('/setup-assistant/agent/finalize', request)
}

export async function fetchSetupAssistantState(): Promise<{ state: Record<string, unknown> }> {
  return getJson<{ state: Record<string, unknown> }>('/setup-assistant/state')
}

export async function fetchModelDownloadStatuses(): Promise<SetupModelDownloadStatusResponse> {
  return getJson<SetupModelDownloadStatusResponse>('/models/download/status')
}

