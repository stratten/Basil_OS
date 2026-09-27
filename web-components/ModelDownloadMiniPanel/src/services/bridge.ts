import type { FontConfig, InitMessage, PanelSnapshot, SwiftMessage, ThemeConfig } from '../types'

export const modelDownloadPanelBridgeProtocolVersion = 1

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: {
        modelDownloadPanelBridge?: {
          postMessage: (message: SwiftMessage & { protocolVersion: number }) => void
        }
      }
    }
    basilModelDownloadPanel?: {
      onInit: (config: InitMessage) => void
      onSnapshot: (snapshot: PanelSnapshot) => void
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void
    }
  }
}

let initHandler: ((config: InitMessage) => void) | undefined
let snapshotHandler: ((snapshot: PanelSnapshot) => void) | undefined
let themeHandler: ((theme: ThemeConfig, fonts: FontConfig) => void) | undefined
let pendingInit: InitMessage | undefined

export function registerInitHandler(handler: (config: InitMessage) => void) {
  initHandler = handler
  if (pendingInit) {
    handler(pendingInit)
    pendingInit = undefined
  }
}

export function registerSnapshotHandler(handler: (snapshot: PanelSnapshot) => void) {
  snapshotHandler = handler
}

export function registerThemeHandler(handler: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeHandler = handler
}

window.basilModelDownloadPanel = {
  onInit(config) {
    if (initHandler) {
      initHandler(config)
      return
    }
    pendingInit = config
  },
  onSnapshot(snapshot) {
    snapshotHandler?.(snapshot)
  },
  onThemeChanged(theme, fonts) {
    themeHandler?.(theme, fonts)
  },
}

function postToSwift(message: SwiftMessage) {
  window.webkit?.messageHandlers?.modelDownloadPanelBridge?.postMessage({
    ...message,
    protocolVersion: modelDownloadPanelBridgeProtocolVersion,
  })
}

export function notifyRendererReady() {
  postToSwift({ type: 'rendererReady' })
}

export function dismissPanel() {
  postToSwift({ type: 'dismiss' })
}

export function retryModel(modelId: string) {
  postToSwift({ type: 'retryModel', modelId })
}

export function cancelModel(modelId: string) {
  postToSwift({ type: 'cancelModel', modelId })
}

export function requestResize(width: number, height: number) {
  postToSwift({ type: 'requestResize', width, height })
}
