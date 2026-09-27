// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyCustomModelsReady,
  onCustomModelsEvent,
  requestCreateModel,
  requestDeleteModel,
  requestDownloadModel,
  requestFetchGGUFMetadata,
  requestFetchLocalGGUFMetadata,
  requestPickLocalFile,
  requestProbeHFRepo,
  requestTestConnection,
  requestUpdateModel,
} from './customModelsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilCustomModelsBridge: { postMessage } } }
})

describe('customModelsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyCustomModelsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestCreateModel with the full payload spread', () => {
    const id = requestCreateModel({
      modelId: 'my-model', displayName: 'My Model', handler: 'openai_compatible',
      baseUrl: 'http://localhost:11434/v1', modelIdentifier: 'llama-3.3', contextWindow: 8192,
      maxOutputTokens: 4096, requiresAuth: false, features: ['streaming'],
    })
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestCreateModel', requestId: id, modelId: 'my-model', displayName: 'My Model',
      handler: 'openai_compatible', baseUrl: 'http://localhost:11434/v1', modelIdentifier: 'llama-3.3',
      contextWindow: 8192, maxOutputTokens: 4096, requiresAuth: false, features: ['streaming'],
    })
  })

  it('sends requestUpdateModel with modelId and payload spread', () => {
    const id = requestUpdateModel('my-model', {
      displayName: 'Renamed', contextWindow: 4096, maxOutputTokens: 2048, requiresAuth: false, features: [],
    })
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestUpdateModel', requestId: id, modelId: 'my-model', displayName: 'Renamed',
      contextWindow: 4096, maxOutputTokens: 2048, requiresAuth: false, features: [],
    })
  })

  it('sends requestDeleteModel with both checkbox booleans', () => {
    const id = requestDeleteModel('my-model', true, false)
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestDeleteModel', requestId: id, modelId: 'my-model', deleteFiles: true, clearHFCache: false,
    })
  })

  it('sends requestDownloadModel with filename', () => {
    const id = requestDownloadModel('llama-gguf', 'model.Q4_K_M.gguf')
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestDownloadModel', requestId: id, modelId: 'llama-gguf', filename: 'model.Q4_K_M.gguf',
    })
  })
  it('sends requestTestConnection without apiKey when omitted', () => {
    const id = requestTestConnection({ handler: 'openai_compatible', baseUrl: 'http://localhost:11434/v1', modelIdentifier: 'llama-3.3' })
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestTestConnection', requestId: id, handler: 'openai_compatible',
      baseUrl: 'http://localhost:11434/v1', modelIdentifier: 'llama-3.3',
    })
  })

  it('sends requestProbeHFRepo with url', () => {
    const id = requestProbeHFRepo('TheBloke/Llama-2-7B-GGUF')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestProbeHFRepo', requestId: id, url: 'TheBloke/Llama-2-7B-GGUF' })
  })

  it('sends requestFetchGGUFMetadata with repoId and filename', () => {
    const id = requestFetchGGUFMetadata('TheBloke/Llama-2-7B-GGUF', 'llama-2-7b.Q4_K_M.gguf')
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestFetchGGUFMetadata', requestId: id, repoId: 'TheBloke/Llama-2-7B-GGUF', filename: 'llama-2-7b.Q4_K_M.gguf',
    })
  })

  it('sends requestFetchLocalGGUFMetadata with filePath', () => {
    const id = requestFetchLocalGGUFMetadata('/Users/test/model.gguf')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestFetchLocalGGUFMetadata', requestId: id, filePath: '/Users/test/model.gguf' })
  })

  it('sends requestPickLocalFile with only a requestId', () => {
    const id = requestPickLocalFile()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestPickLocalFile', requestId: id })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilCustomModels!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onCustomModelsEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
    window.basilCustomModels!.onEvent({ type: 'loadError', message: 'after' })
    expect(received).toEqual(['boom'])
  })

  it('delivers localFilePicked and hfProbeResult events to the live handler', () => {
    const received: string[] = []
    onCustomModelsEvent((event) => {
      if (event.type === 'localFilePicked') received.push(event.path)
      if (event.type === 'hfProbeResult') received.push(event.repoId)
    })
    window.basilCustomModels!.onEvent({ type: 'localFilePicked', requestId: 'r1', path: '/tmp/model.gguf' })
    window.basilCustomModels!.onEvent({
      type: 'hfProbeResult', requestId: 'r2', repoId: 'org/repo', ggufFiles: [], modelMetadata: null, error: null,
    })
    expect(received).toEqual(['/tmp/model.gguf', 'org/repo'])
  })
})
