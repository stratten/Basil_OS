import { requestCancelGitHubDeviceFlow, requestOpenExternalUrl } from '../services/connectionsBridge'
import type { ConnectionsSettingsFields } from '../types'

interface ConnectionSignInProgressProps {
  fields: ConnectionsSettingsFields
  onTrackRequest: (id: string) => void
  onContinueInBackground: () => void
  showPendingFlow?: boolean
}

export function ConnectionSignInProgress({
  fields,
  onTrackRequest,
  onContinueInBackground,
  showPendingFlow = true,
}: ConnectionSignInProgressProps) {
  const deviceFlow = fields.githubDeviceFlow

  if (deviceFlow) {
    return (
      <div className="connections-device-flow" role="status">
        <p className="connections-device-flow-title">Authorize GitHub</p>
        <p className="connections-device-flow-hint">Enter this code at GitHub. Basil will continue automatically after approval.</p>
        <div className="connections-device-flow-code-row">
          <span className="connections-device-flow-code">{deviceFlow.userCode}</span>
          <button
            type="button"
            className="secondary-button"
            onClick={() => navigator.clipboard.writeText(deviceFlow.userCode)}
          >
            Copy Code
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => onTrackRequest(requestOpenExternalUrl(deviceFlow.verificationUri))}
          >
            Open GitHub
          </button>
          {fields.isPollingGitHubDeviceFlow && (
            <button
              type="button"
              className="connections-device-flow-cancel"
              onClick={() => onTrackRequest(requestCancelGitHubDeviceFlow())}
            >
              Cancel
            </button>
          )}
        </div>
        {fields.isPollingGitHubDeviceFlow && (
          <p className="connections-device-flow-waiting">Waiting for authorization...</p>
        )}
      </div>
    )
  }

  if (showPendingFlow && fields.pendingFlowFriendlyName) {
    return (
      <div className="connections-device-flow" role="status">
        <p className="connections-device-flow-title">Waiting for {fields.pendingFlowFriendlyName}</p>
        <p className="connections-device-flow-hint">
          {fields.statusMessage ?? `Complete sign-in in your browser to finish adding ${fields.pendingFlowFriendlyName}.`}
        </p>
        <button type="button" className="secondary-button" onClick={onContinueInBackground}>Continue in Background</button>
      </div>
    )
  }

  return null
}
