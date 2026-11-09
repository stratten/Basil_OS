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
  | 'setupAccountLogin'
  | 'setupAccountSignup'
  | 'setupAccountGoogleSignIn'
  | 'setupAccountOpenPaymentSetup'
  | 'setupAccountRefresh'
  | 'closeSetupAssistant'
  | 'minimizeSetupAssistant'
  | 'collapseSetupAssistant'
  | 'expandSetupAssistant'
  | 'growSetupAssistantForConversation'
  | 'reportProblem'
  | 'showDiagnosticLogs'
  | 'evaluateSetupHotkeys'
  | 'applySetupHotkey'
  | 'captureSetupHotkey'
  | 'cancelSetupHotkeyCapture'
  | 'resolveSetupHotkeys'

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

/** Asks the app to open its Report a problem flow. `detail` is a native return code or similar, never conversation or prompt text. */
export function reportProblem(source: string, detail?: string) {
  postBridgeMessage('reportProblem', { source, detail })
}

/** Asks the app to save a redacted diagnostics bundle and show it in Finder, without opening an issue. */
export function showDiagnosticLogs(source: string, detail?: string) {
  postBridgeMessage('showDiagnosticLogs', { source, detail })
}

export function growSetupAssistantForConversation() {
  postBridgeMessage('growSetupAssistantForConversation')
}

/** True inside the Basil app window, false in a plain browser. The hotkey conflict check only works with the app. */
export function isSetupNativeBridgeAvailable(): boolean {
  return swiftBridge.isAvailable()
}

export interface SetupHotkeyBindingPayload {
  key: string
  enabled: boolean
  modifiers: string[]
  isDoublePress: boolean
  doublePressKey: string | null
}

/** Reads the person's current hotkeys and checks each against this Mac's own shortcuts and Basil's other hotkeys. */
export function evaluateSetupHotkeys(): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('evaluateSetupHotkeys')
}

/** Saves one hotkey. Keys that clash are not saved unless `acknowledgeConflict` is true. With `checkOnly`, nothing is saved and `saved` in the answer means the keys would be accepted. */
export function applySetupHotkey(
  id: string,
  binding: SetupHotkeyBindingPayload,
  acknowledgeConflict: boolean,
  checkOnly = false,
): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('applySetupHotkey', checkOnly ? { id, binding, acknowledgeConflict, checkOnly } : { id, binding, acknowledgeConflict })
}

/** Starts the app's key recorder. The promise resolves when keys are pressed or the recording is canceled. */
export function captureSetupHotkey(id: string): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('captureSetupHotkey', { id })
}

/** Ends a recording the person walked away from. */
export function cancelSetupHotkeyCapture() {
  postBridgeMessage('cancelSetupHotkeyCapture')
}

/** Switches every hotkey that clashes to a free replacement, in one save, except the ones in `excludeIds`, which the person already decided on. Used by express setup. */
export function resolveSetupHotkeys(excludeIds: readonly string[] = []): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('resolveSetupHotkeys', excludeIds.length > 0 ? { excludeIds } : undefined)
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

export function requestAccountLogin(email: string, password: string): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('setupAccountLogin', { email, password })
}

export function requestAccountSignup(
  email: string,
  password: string,
  confirmPassword: string,
): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('setupAccountSignup', { email, password, confirmPassword })
}

/** Opens Google sign-in in the system browser; the native app finishes the sign-in when the browser returns to basil://auth/callback. */
export function requestAccountGoogleSignIn(): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('setupAccountGoogleSignIn')
}

/** Opens the Stripe payment page in the system browser. */
export function requestAccountPaymentSetup(): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('setupAccountOpenPaymentSetup')
}

/** Re-reads the signed-in account from the auth service and pushes its token to the backend so the next options fetch sees it. */
export function requestAccountRefresh(): Promise<SetupBridgeActionResult> {
  return postBridgeMessageWithResult('setupAccountRefresh')
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

