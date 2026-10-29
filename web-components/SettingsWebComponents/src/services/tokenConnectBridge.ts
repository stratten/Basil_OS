import { postToSwiftHandler } from '@shared/swiftBridge'

export type TokenConnectRequest = {
  requestId: string
  serverUrl: string
  host: string
  friendlyName: string
  description: string | null
  existingNames: string[]
  alreadyConnectedAs: string | null
}

export type TokenConnectNativeEvent =
  | { type: 'init'; request: TokenConnectRequest }
  | { type: 'working' }
  | { type: 'failed'; message: string }

type OutgoingTokenConnectMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestConnect'; requestId: string; friendlyName: string; description?: string; bearerToken: string }
  | { type: 'requestCancel'; requestId: string }

declare global {
  interface Window {
    basilTokenConnect?: {
      onEvent: (event: TokenConnectNativeEvent) => void
    }
  }
}

type EventHandler = (event: TokenConnectNativeEvent) => void

let queuedEvents: TokenConnectNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: TokenConnectNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilTokenConnect = { onEvent: dispatch }

export function onTokenConnectEvent(handler: EventHandler) {
  liveHandler = handler
  const queued = queuedEvents
  queuedEvents = []
  queued.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

export function notifyTokenConnectReady() {
  postToSwiftHandler('basilTokenConnectBridge', { type: 'reactReady', protocolVersion: 1 } satisfies OutgoingTokenConnectMessage)
}

export function requestTokenConnect(requestId: string, friendlyName: string, bearerToken: string, description?: string) {
  const message: OutgoingTokenConnectMessage = { type: 'requestConnect', requestId, friendlyName, bearerToken }
  if (description) message.description = description
  postToSwiftHandler('basilTokenConnectBridge', message)
}

export function requestTokenConnectCancel(requestId: string) {
  postToSwiftHandler('basilTokenConnectBridge', { type: 'requestCancel', requestId } satisfies OutgoingTokenConnectMessage)
}

export function __resetTokenConnectBridgeForTests() {
  queuedEvents = []
  liveHandler = null
}
