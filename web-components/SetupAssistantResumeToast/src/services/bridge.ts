import { createSwiftBridge } from '@shared/swiftBridge'
import type { FontConfig, InitMessage, SwiftMessage, ThemeConfig } from '../types'

export const setupAssistantResumeToastBridgeProtocolVersion = 1

declare global {
  interface Window {
    basilSetupAssistantResumeToast?: {
      onInit: (config: InitMessage) => void
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void
    }
  }
}

let initHandler: ((config: InitMessage) => void) | undefined
let themeHandler: ((theme: ThemeConfig, fonts: FontConfig) => void) | undefined
let pendingInit: InitMessage | undefined

export function registerInitHandler(handler: (config: InitMessage) => void) {
  initHandler = handler
  if (pendingInit) {
    handler(pendingInit)
    pendingInit = undefined
  }
}

export function registerThemeHandler(handler: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeHandler = handler
}

window.basilSetupAssistantResumeToast = {
  onInit(config) {
    if (initHandler) {
      initHandler(config)
      return
    }
    pendingInit = config
  },
  onThemeChanged(theme, fonts) {
    themeHandler?.(theme, fonts)
  },
}

const swiftBridge = createSwiftBridge<SwiftMessage & { protocolVersion: number }>('setupAssistantResumeToastBridge')

function postToSwift(message: SwiftMessage) {
  swiftBridge.post({
    ...message,
    protocolVersion: setupAssistantResumeToastBridgeProtocolVersion,
  })
}

export function notifyRendererReady() {
  postToSwift({ type: 'rendererReady' })
}

export function requestResize(width: number, height: number) {
  postToSwift({ type: 'requestResize', width, height })
}

export function resumeSetup() {
  postToSwift({ type: 'resume' })
}

export function remindLater() {
  postToSwift({ type: 'remindLater' })
}

export function dontRemind() {
  postToSwift({ type: 'dontRemind' })
}
