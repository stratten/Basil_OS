import { createSwiftBridge } from '@shared/swiftBridge'
import type { SetupAction, SetupTaskOffer } from '@/types'

type BridgeMessageName =
  | 'setupAssistantReady'
  | 'requestPermissionStatus'
  | 'requestPermission'
  | 'openSystemSettings'
  | 'restartApplication'
  | 'continueSetupAssistant'
  | 'launchAgentTaskOffer'
  | 'launchAssistantSessionOffer'
  | 'openConnectionAuth'
  | 'saveSetupReferencePdf'
  | 'closeSetupAssistant'
  | 'minimizeSetupAssistant'
  | 'collapseSetupAssistant'
  | 'expandSetupAssistant'

interface SetupAssistantBridgeMessage {
  version: 1
  name: BridgeMessageName
  payload?: Record<string, unknown>
  requestId?: string
}

export interface SetupBridgeActionResult {
  requestId: string
  status: 'executed' | 'failed'
  message: string
  resultPayload?: Record<string, unknown>
}

const swiftBridge = createSwiftBridge<SetupAssistantBridgeMessage>('setupAssistant')

function postBridgeMessage(name: BridgeMessageName, payload?: Record<string, unknown>) {
  swiftBridge.post({
    version: 1,
    name,
    payload,
  })
}

function postBridgeMessageWithResult(
  name: BridgeMessageName,
  payload?: Record<string, unknown>,
): Promise<SetupBridgeActionResult> {
  if (!swiftBridge.isAvailable()) {
    return Promise.reject(new Error(`Native setup bridge is unavailable for '${name}'.`))
  }

  const requestId = `${name}-${Date.now()}-${Math.random().toString(36).slice(2)}`

  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      window.removeEventListener('setupAssistantActionResult', handleResult)
      reject(new Error(`Setup action '${name}' did not receive a native response.`))
    }, 30_000)

    function handleResult(event: Event) {
      const detail = (event as CustomEvent<SetupBridgeActionResult>).detail
      if (!detail || detail.requestId !== requestId) {
        return
      }
      window.clearTimeout(timeoutId)
      window.removeEventListener('setupAssistantActionResult', handleResult)
      if (detail.status === 'failed') {
        reject(new Error(detail.message))
        return
      }
      resolve(detail)
    }

    window.addEventListener('setupAssistantActionResult', handleResult)
    swiftBridge.post({
      version: 1,
      name,
      payload,
      requestId,
    })
  })
}

export function notifySetupAssistantReady() {
  postBridgeMessage('setupAssistantReady')
}

export function requestPermission(kind: string) {
  postBridgeMessage('requestPermission', { kind })
}

export function openSystemSettings(kind?: string) {
  postBridgeMessage('openSystemSettings', { kind })
}

export function restartApplication() {
  postBridgeMessage('restartApplication')
}

export function continueSetupAssistant() {
  postBridgeMessage('continueSetupAssistant')
}

export function closeSetupAssistant() {
  postBridgeMessage('closeSetupAssistant')
}

export function minimizeSetupAssistant() {
  postBridgeMessage('minimizeSetupAssistant')
}

export function collapseSetupAssistant() {
  postBridgeMessage('collapseSetupAssistant')
}

export function expandSetupAssistant() {
  postBridgeMessage('expandSetupAssistant')
}

export function launchAgentTaskOffer(offer: SetupTaskOffer): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('launchAgentTaskOffer', { offer })
}

export function launchAgentTaskAction(action: SetupAction): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('launchAgentTaskOffer', {
    offer: {
      ...action.payload,
      id: action.id,
    },
  })
}

export function launchAssistantSessionOffer(action: SetupAction): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('launchAssistantSessionOffer', { action })
}

export function openConnectionAuth(connection: Record<string, unknown>): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('openConnectionAuth', connection)
}

export function saveSetupReferencePdf(
  base64Pdf: string,
  suggestedFilename: string,
): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('saveSetupReferencePdf', {
    base64Pdf,
    suggestedFilename,
  })
}

export type SetupAgentTaskObservationKind = 'progress' | 'terminal'

export interface SetupAgentTaskObservation {
  agentTaskId: string
  kind: SetupAgentTaskObservationKind
  status: string
  currentStep?: string
  resultMessage?: string
  errorMessage?: string
  severity?: string
  outcome?: string
}

/**
 * Subscribe to native-emitted observations about agent tasks launched from
 * setup. The Swift host polls /api/v1/agent-tasks/{id} on the user's behalf
 * and dispatches a custom event for each meaningful state change (gated on
 * status / result-message change with a 10 second floor) and for the final
 * terminal state. The setup store uses these to re-engage the setup agent
 * automatically so the conversation stays live with the task. Returns an
 * unsubscribe function the caller can invoke on teardown.
 */
export function onAgentTaskObservation(
  handler: (observation: SetupAgentTaskObservation) => void,
): () => void {
  function listener(event: Event) {
    const detail = (event as CustomEvent<SetupAgentTaskObservation>).detail
    if (!detail || !detail.agentTaskId || !detail.kind || !detail.status) {
      return
    }
    handler(detail)
  }
  window.addEventListener('setupAssistantAgentTaskObservation', listener)
  return () => {
    window.removeEventListener('setupAssistantAgentTaskObservation', listener)
  }
}

// Setup-launched Dill (launch_assistant_session) only emits a terminal
// observation today — Dill drafts complete in seconds and the in-flight
// streaming output is already visible in the Dill widget, so progress
// commentary from the setup agent would compete with the widget for
// attention. The 'terminal' literal mirrors the shape used by the
// agent-task observation so the downstream listener-to-outcome mapping
// stays symmetric and easy to extend later if progress events become
// useful (e.g., for long-running Dill flows).
export type SetupAssistantSessionObservationKind = 'terminal'

export interface SetupAssistantSessionObservation {
  assistantSessionId: string
  kind: SetupAssistantSessionObservationKind
  status: string
  resultText?: string
  errorMessage?: string
}

/**
 * Subscribe to native-emitted observations about Dill assistant sessions
 * launched from setup. The Swift host (AssistantSessionWindowController)
 * observes the AssistantSessionViewModel's `$assistantSessionStatus`
 * publisher and dispatches a single 'terminal' event when the session
 * transitions to .completed or .failed. The setup store uses this to
 * re-engage the setup agent so it can narrate Dill's draft outcome and
 * propose follow-ups — symmetric to the agent-task observation flow.
 * Returns an unsubscribe function the caller can invoke on teardown.
 */
export function onAssistantSessionObservation(
  handler: (observation: SetupAssistantSessionObservation) => void,
): () => void {
  function listener(event: Event) {
    const detail = (event as CustomEvent<SetupAssistantSessionObservation>).detail
    if (!detail || !detail.assistantSessionId || !detail.kind || !detail.status) {
      return
    }
    handler(detail)
  }
  window.addEventListener('setupAssistantAssistantSessionObservation', listener)
  return () => {
    window.removeEventListener('setupAssistantAssistantSessionObservation', listener)
  }
}

