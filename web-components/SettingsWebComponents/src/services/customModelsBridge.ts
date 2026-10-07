import { postToSwiftHandler } from '@shared/swiftBridge'
import type { CustomModelsNativeEvent } from '../types'

export interface CreateModelPayload {
  modelId: string
  displayName: string
  handler: string
  baseUrl?: string
  modelIdentifier?: string
  modelPath?: string
  downloadUrl?: string
  contextWindow: number
  maxOutputTokens: number
  requiresAuth: boolean
  apiKey?: string
  features: string[]
  toolRendering?: string
  toolCallFormat?: string
  serverType?: string
  description?: string
  fileSize?: number
  fileSizeHuman?: string
}

export interface UpdateModelPayload {
  displayName: string
  handler?: string
  baseUrl?: string
  modelIdentifier?: string
  modelPath?: string
  downloadUrl?: string
  contextWindow: number
  maxOutputTokens: number
  requiresAuth: boolean
  apiKey?: string
  features: string[]
  toolRendering?: string
  toolCallFormat?: string
  serverType?: string
  description?: string
}

export interface TestConnectionPayload {
  handler: string
  baseUrl: string
  modelIdentifier: string
  apiKey?: string
}

type OutgoingMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | ({ type: 'requestCreateModel'; requestId: string } & CreateModelPayload)
  | ({ type: 'requestUpdateModel'; requestId: string; modelId: string } & UpdateModelPayload)
  | { type: 'requestDeleteModel'; requestId: string; modelId: string; deleteFiles: boolean; clearHFCache: boolean }
  | { type: 'requestDownloadModel'; requestId: string; modelId: string; filename: string }
  | ({ type: 'requestTestConnection'; requestId: string } & TestConnectionPayload)
  | { type: 'requestProbeHFRepo'; requestId: string; url: string }
  | { type: 'requestFetchGGUFMetadata'; requestId: string; repoId: string; filename: string }
  | { type: 'requestFetchLocalGGUFMetadata'; requestId: string; filePath: string }
  | { type: 'requestPickLocalFile'; requestId: string }

declare global {
  interface Window {
    basilCustomModels?: {
      onEvent: (event: CustomModelsNativeEvent) => void
    }
  }
}

type EventHandler = (event: CustomModelsNativeEvent) => void

let queuedEvents: CustomModelsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: CustomModelsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilCustomModels = { onEvent: dispatch }

export function onCustomModelsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMessage) {
  postToSwiftHandler('basilCustomModelsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyCustomModelsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestCreateModel(payload: CreateModelPayload): string {
  const requestIdValue = requestId('requestCreateModel')
  postMessage({ type: 'requestCreateModel', requestId: requestIdValue, ...payload })
  return requestIdValue
}

export function requestUpdateModel(modelId: string, payload: UpdateModelPayload): string {
  const requestIdValue = requestId('requestUpdateModel')
  postMessage({ type: 'requestUpdateModel', requestId: requestIdValue, modelId, ...payload })
  return requestIdValue
}

export function requestDeleteModel(modelId: string, deleteFiles: boolean, clearHFCache: boolean): string {
  const requestIdValue = requestId('requestDeleteModel')
  postMessage({ type: 'requestDeleteModel', requestId: requestIdValue, modelId, deleteFiles, clearHFCache })
  return requestIdValue
}

export function requestDownloadModel(modelId: string, filename: string): string {
  const requestIdValue = requestId('requestDownloadModel')
  postMessage({ type: 'requestDownloadModel', requestId: requestIdValue, modelId, filename })
  return requestIdValue
}

export function requestTestConnection(payload: TestConnectionPayload): string {
  const requestIdValue = requestId('requestTestConnection')
  postMessage({ type: 'requestTestConnection', requestId: requestIdValue, ...payload })
  return requestIdValue
}

export function requestProbeHFRepo(url: string): string {
  const requestIdValue = requestId('requestProbeHFRepo')
  postMessage({ type: 'requestProbeHFRepo', requestId: requestIdValue, url })
  return requestIdValue
}

export function requestFetchGGUFMetadata(repoId: string, filename: string): string {
  const requestIdValue = requestId('requestFetchGGUFMetadata')
  postMessage({ type: 'requestFetchGGUFMetadata', requestId: requestIdValue, repoId, filename })
  return requestIdValue
}

export function requestFetchLocalGGUFMetadata(filePath: string): string {
  const requestIdValue = requestId('requestFetchLocalGGUFMetadata')
  postMessage({ type: 'requestFetchLocalGGUFMetadata', requestId: requestIdValue, filePath })
  return requestIdValue
}

export function requestPickLocalFile(): string {
  const requestIdValue = requestId('requestPickLocalFile')
  postMessage({ type: 'requestPickLocalFile', requestId: requestIdValue })
  return requestIdValue
}
