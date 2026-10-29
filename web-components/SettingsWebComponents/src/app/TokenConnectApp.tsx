import { useEffect, useState } from 'react'
import { AgentTokenConnectModal } from '../components/AgentTokenConnectModal'
import {
  notifyTokenConnectReady,
  onTokenConnectEvent,
  requestTokenConnect,
  requestTokenConnectCancel,
  type TokenConnectRequest,
} from '../services/tokenConnectBridge'
import '../styles/settings-elements.css'
import '../styles/connections-settings.css'

export function TokenConnectApp() {
  const [request, setRequest] = useState<TokenConnectRequest | null>(null)
  const [isWorking, setIsWorking] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    const unsubscribe = onTokenConnectEvent((event) => {
      if (event.type === 'init') {
        setRequest(event.request)
        setIsWorking(false)
        setErrorMessage(null)
        return
      }
      if (event.type === 'working') {
        setIsWorking(true)
        setErrorMessage(null)
        return
      }
      if (event.type === 'failed') {
        setIsWorking(false)
        setErrorMessage(event.message)
      }
    })
    notifyTokenConnectReady()
    return unsubscribe
  }, [])

  if (!request) {
    return <p className="connections-panel-status" role="status">Preparing the connection window…</p>
  }

  return (
    <AgentTokenConnectModal
      request={request}
      isWorking={isWorking}
      errorMessage={errorMessage}
      onConnect={(friendlyName, description, token) => {
        setIsWorking(true)
        setErrorMessage(null)
        requestTokenConnect(request.requestId, friendlyName, token, description)
      }}
      onCancel={() => requestTokenConnectCancel(request.requestId)}
    />
  )
}
