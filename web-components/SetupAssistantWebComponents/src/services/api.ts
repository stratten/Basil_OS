import { createContextImportClient } from '@shared/contextImportClient'
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
  SetupLocalModelDownloadProgress,
  SetupModelDownloadStatusResponse,
  SetupToolCall,
  SetupToolCallValidationResponse,
  SetupAgentOutput,
  SetupWrapUpProposal,
} from '@/types'
import type { ComfortLevel, ExpressApplyResult, ExpressPlan, SetupReceipt } from '@/components/express/expressTypes'

export type SetupAssistantSkipRequest = SetupAssistantCompletionRequest

const API_BASE = window.basilSetupAssistantConfig?.apiBaseUrl ?? ''

/** The shared personal context import, pointed at the backend this setup window was given. */
export function setupContextImportClient() {
  return createContextImportClient(API_BASE)
}
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

export interface HotkeyBindingSnapshot {
  key: string
  enabled: boolean
  modifiers: string[]
  is_double_press?: boolean
  double_press_key?: string | null
}

export async function fetchHotkeyBindings(): Promise<Record<string, HotkeyBindingSnapshot>> {
  const response = await getJson<{ settings: Record<string, HotkeyBindingSnapshot> }>('/settings/hotkeys')
  return response.settings
}

export interface InteractionStyleOption {
  id: string
  label: string
}

export interface InteractionStyleGroup {
  id: string
  title: string
  multiple: boolean
  options: InteractionStyleOption[]
}

export type InteractionStyleSelections = Record<string, string[]>

export interface InteractionStyleSaveResult {
  saved: boolean
  instructions: string[]
}

export async function fetchInteractionStyleCatalog(): Promise<InteractionStyleGroup[]> {
  const response = await getJson<{ groups: InteractionStyleGroup[] }>('/setup-assistant/interaction-style')
  return Array.isArray(response.groups) ? response.groups : []
}

export async function saveInteractionStyle(selections: InteractionStyleSelections): Promise<InteractionStyleSaveResult> {
  return postJson<InteractionStyleSaveResult>('/setup-assistant/interaction-style', { selections })
}

export async function fetchSetupAgentContract(): Promise<SetupAgentContractResponse> {
  return getJson<SetupAgentContractResponse>('/setup-assistant/agent-contract')
}

/**
 * Pass `checkAccount` only after the user has chosen Basil Cloud: it makes the app read the account from the Keychain, which can show a macOS permission prompt.
 * `localModelId` names the local model the Local route should describe. Only a validation build honors it; every other build ignores it.
 */
export async function fetchModelAccessOptions(
  checkAccount = false,
  localModelId: string | null = null,
): Promise<SetupAgentModelAccessOptionsResponse> {
  const query = new URLSearchParams()
  if (checkAccount) query.set('check_account', 'true')
  if (localModelId) query.set('local_model_id', localModelId)
  const queryString = query.toString()
  return getJson<SetupAgentModelAccessOptionsResponse>(
    `/setup-assistant/model-access/options${queryString ? `?${queryString}` : ''}`,
  )
}

/** Validation builds only: copies an installed model from the normal Basil's model folder into this session. Progress is read from the same download progress routes as a download. */
export async function copyLocalModelFromNormalBasil(modelType: string, variant: string): Promise<{ model_id: string, status: string }> {
  return postJson<{ model_id: string, status: string }>('/setup-assistant/model-access/validation/copy-model', {
    model_type: modelType,
    variant,
  })
}

export async function startLocalModelDownload(modelType: string, variant: string): Promise<{ model_id: string, status: string }> {
  return postJson<{ model_id: string, status: string }>('/models/download', {
    request: { model_type: modelType, variant },
  })
}

export async function fetchLocalModelDownloadProgress(
  modelType: string,
  variant: string,
): Promise<SetupLocalModelDownloadProgress> {
  return getJson<SetupLocalModelDownloadProgress>(
    `/models/predefined/${encodeURIComponent(modelType)}/${encodeURIComponent(variant)}/download/progress`,
  )
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

/** What a comfort level would do on this Mac, with disk and network checks. Changes nothing. */
export async function fetchExpressPlan(comfort: ComfortLevel): Promise<ExpressPlan> {
  return getJson<ExpressPlan>(`/setup-assistant/express/plan?comfort=${encodeURIComponent(comfort)}`)
}

/** Starts the ticked downloads and turns on the ticked settings. The backend rebuilds the plan, so only ids are sent. */
export async function applyExpressPlan(comfort: ComfortLevel, selectedItemIds: string[]): Promise<ExpressApplyResult> {
  return postJson<ExpressApplyResult>('/setup-assistant/express/apply', {
    comfort,
    selected_item_ids: selectedItemIds,
  })
}

/** What is on right now, read from the real settings and installed models. */
export async function fetchExpressReceipt(): Promise<SetupReceipt> {
  return getJson<SetupReceipt>('/setup-assistant/express/receipt')
}

export async function fetchModelDownloadStatuses(): Promise<SetupModelDownloadStatusResponse> {
  return getJson<SetupModelDownloadStatusResponse>('/models/download/status')
}



export interface SmallerReasoningModelResult {
  status: 'switched' | 'downloading' | 'unavailable'
  model_id: string | null
  message: string
}

/** Moves Basil to the smaller local model its registry entry names. Safe to call again while the download runs: it reports `switched` once the model is installed. */
export async function switchToSmallerReasoningModel(): Promise<SmallerReasoningModelResult> {
  return postJson<SmallerReasoningModelResult>('/onboarding/use-smaller-reasoning-model', {})
}

export interface StarterDownloadProgressRecord {
  status: string
  progress: number
  description?: string
  /** The registry's name for the model, such as "Whisper Tiny (English)". */
  display_name?: string
  /** True only in a fresh validation session whose normal Basil holds a complete copy of this model. */
  can_copy_from_normal_basil?: boolean
  /** Bytes received so far and bytes in the whole download. Present only once a download has reported them. */
  total_downloaded?: number
  total_size?: number
  /** What the backend is doing right now, such as "Waiting for Hugging Face to start sending data (20s)...". Present only for a queued or downloading model. */
  message?: string
}

export interface StarterDownloadProgress {
  all_complete: boolean
  models: Record<string, StarterDownloadProgressRecord>
}

/** Reads the status of every starter download: the reasoning model and the two voice models. */
export async function fetchStarterDownloadProgress(): Promise<StarterDownloadProgress> {
  return getJson<StarterDownloadProgress>('/onboarding/download-progress')
}

export interface LocalModelComparisonRow {
  modelId: string
  displayName: string
  size: string
  speedRating: number
  accuracyRating: number
  recommendedRam: string
  systemCompatible: boolean
}

export interface LocalModelComparison {
  models: LocalModelComparisonRow[]
  totalRamGB: number | null
}

interface ModelRecommendationsResponse {
  recommendations?: LocalModelComparisonRow[]
  systemInfo?: { totalRamGB?: number }
}

/** Reads the local reasoning models Basil would recommend for this Mac, with the registry's size, speed, accuracy and memory fields. */
export async function fetchLocalModelComparison(maxModels = 4): Promise<LocalModelComparison> {
  const response = await postJson<ModelRecommendationsResponse>('/models/recommendations', {
    capability: 'reasoning',
    preference: 'balanced',
    max_recommendations: maxModels,
  })
  return {
    models: response.recommendations ?? [],
    totalRamGB: typeof response.systemInfo?.totalRamGB === 'number' ? response.systemInfo.totalRamGB : null,
  }
}
