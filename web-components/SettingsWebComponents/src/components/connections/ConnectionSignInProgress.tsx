import { useEffect, useState } from 'react'
import { useCopiedFlag } from '@shared/useCopyFeedback'
import { requestCancelGitHubDeviceFlow, requestCancelPendingOAuthFlow, requestOpenExternalUrl } from '../../services/connections/connectionsBridge'
import type { ConnectionsSettingsFields } from '../../types'

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
  const [codeCopied, flashCodeCopied] = useCopiedFlag()
  const deviceFlow = fields.githubDeviceFlow
  const deviceUserCode = deviceFlow?.userCode ?? null
  const [autoCopiedCode, setAutoCopiedCode] = useState<string | null>(null)

  // Put the code on the clipboard the moment it is shown, so the person can paste it at GitHub. The hint below only says so once the write has actually succeeded.
  useEffect(() => {
    if (!deviceUserCode || !navigator.clipboard) return undefined
    let canceled = false
    navigator.clipboard.writeText(deviceUserCode).then(
      () => { if (!canceled) setAutoCopiedCode(deviceUserCode) },
      () => undefined,
    )
    return () => { canceled = true }
  }, [deviceUserCode])

  if (deviceFlow) {
    return (
      <div className="connections-device-flow" role="status">
        <p className="connections-device-flow-title">Authorize GitHub</p>
        <p className="connections-device-flow-hint">
          {autoCopiedCode === deviceFlow.userCode
            ? 'This code is now on your clipboard, replacing what was there. Paste it at GitHub. Basil will continue automatically after approval.'
            : 'Enter this code at GitHub. Basil will continue automatically after approval.'}
        </p>
        <div className="connections-device-flow-code-row">
          <span className="connections-device-flow-code">{deviceFlow.userCode}</span>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              navigator.clipboard.writeText(deviceFlow.userCode).then(() => flashCodeCopied(), () => undefined)
            }}
          >
            {codeCopied ? 'Copied' : 'Copy Code'}
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
        <button
          type="button"
          className="connections-device-flow-cancel"
          onClick={() => onTrackRequest(requestCancelPendingOAuthFlow())}
        >
          Cancel Sign-in
        </button>
      </div>
    )
  }

  return null
}
