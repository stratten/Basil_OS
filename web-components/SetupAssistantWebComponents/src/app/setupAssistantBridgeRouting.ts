import {
  launchAgentTaskAction,
  launchAssistantSessionOffer,
  openConnectionAuth,
} from '@/services/bridge'
import type { SetupAction, SetupToolCall } from '@/types'

// Tool-call routing for approved setup proposals that need to cross the
// Swift bridge instead of going to the backend HTTP layer. Kept as pure
// functions so they're easy to test in isolation and so the proposal
// handler hook stays focused on dispatch + status orchestration rather
// than payload shaping.

const NATIVE_BRIDGE_TOOL_NAMES: ReadonlyArray<string> = [
  'launch_assistant_session',
  'launch_agent_task',
  'start_connection_auth',
]

export function isNativeBridgeToolCall(toolCall: SetupToolCall): boolean {
  return NATIVE_BRIDGE_TOOL_NAMES.includes(toolCall.tool_name)
}

export async function executeNativeBridgeToolCall(toolCall: SetupToolCall) {
  const action = buildSetupActionFromToolCall(toolCall)
  if (toolCall.tool_name === 'launch_assistant_session') {
    return await launchAssistantSessionOffer(action)
  }
  if (toolCall.tool_name === 'launch_agent_task') {
    return await launchAgentTaskAction(action)
  }
  if (toolCall.tool_name === 'start_connection_auth') {
    return await openConnectionAuth(normalizeConnectionPayload(toolCall.payload))
  }
  throw new Error(`I cannot route setup action '${toolCall.tool_name}'.`)
}

function buildSetupActionFromToolCall(toolCall: SetupToolCall): SetupAction {
  return {
    id: toolCall.id,
    kind: toolCall.tool_name as SetupAction['kind'],
    payload: toolCall.payload,
    requires_explicit_approval: true,
    mutates_external_state: toolCall.mutates_external_state,
  }
}

function normalizeConnectionPayload(payload: Record<string, unknown>): Record<string, unknown> {
  return {
    ...payload,
    connectorId: payload.connectorId ?? payload.connector_id,
    serverUrl: payload.serverUrl ?? payload.server_url,
    friendlyName: payload.friendlyName ?? payload.friendly_name,
  }
}
