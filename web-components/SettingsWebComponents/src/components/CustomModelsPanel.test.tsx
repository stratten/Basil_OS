// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CustomModelsPanel } from './CustomModelsPanel'
import type { CustomModelSummary } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

const API_MODEL: CustomModelSummary = {
  modelId: 'my-ollama', displayName: 'My Ollama', handler: 'openai_compatible', isLocal: false,
  baseUrl: 'http://localhost:11434/v1', modelIdentifier: 'llama3.3', modelPath: null, downloadUrl: null,
  contextWindow: 8192, maxOutputTokens: 4096, requiresAuth: false, capabilities: ['reasoning'],
  features: ['streaming'], toolRendering: null, toolCallFormat: null, description: null,
  fileSize: null, fileSizeHuman: null, needsDownload: false,
}

const UNDOWNLOADED_LOCAL_MODEL: CustomModelSummary = {
  modelId: 'llama-gguf', displayName: 'Llama GGUF', handler: 'llama_cpp', isLocal: true,
  baseUrl: null, modelIdentifier: null, modelPath: null, downloadUrl: 'https://huggingface.co/org/repo/resolve/main/model.gguf',
  contextWindow: 4096, maxOutputTokens: 2048, requiresAuth: false, capabilities: ['reasoning'],
  features: [], toolRendering: null, toolCallFormat: null, description: null,
  fileSize: 4_000_000_000, fileSizeHuman: '4.0 GB', needsDownload: true,
}

function sendEvent(event: Record<string, unknown>) {
  act(() => { window.basilCustomModels!.onEvent(event as any) })
}

function sendInit(models: CustomModelSummary[] = [API_MODEL]) {
  sendEvent({ type: 'init', protocolVersion: 1, isLoading: false, models })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilCustomModelsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<CustomModelsPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('CustomModelsPanel', () => {
  it('shows a loading state before init arrives, then sends reactReady', () => {
    expect(container.querySelector('.custom-models-status')?.textContent).toBe('Loading custom models...')
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('renders the empty state with an Add Model button when there are no models', () => {
    sendInit([])
    expect(container.textContent).toContain('No custom models yet.')
  })

  it('renders a model row after init', () => {
    sendInit()
    expect(container.textContent).toContain('My Ollama')
  })

  it('surfaces a native loadError instead of the model list', () => {
    sendEvent({ type: 'loadError', message: 'Backend unreachable' })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Backend unreachable')
    postMessage.mockClear()
    act(() => { Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Retry')?.click() })
    expect(lastMessageOfType('reactReady')).toEqual({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestDeleteModel with checkbox state when the inline confirmation is confirmed', () => {
    sendInit()
    const deleteButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Delete') as HTMLButtonElement
    act(() => { deleteButton.click() })
    const confirmButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Delete' && button.className.includes('delete-confirm-button')) as HTMLButtonElement
    act(() => { confirmButton.click() })
    expect(lastMessageOfType('requestDeleteModel')).toMatchObject({ modelId: 'my-ollama', deleteFiles: false, clearHFCache: false })
  })

  it('shows HuggingFace cache controls for a repository ID from the wizard', () => {
    sendInit([{ ...UNDOWNLOADED_LOCAL_MODEL, downloadUrl: 'TheBloke/Llama-2-7B-GGUF' }])
    const deleteButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Delete') as HTMLButtonElement
    act(() => { deleteButton.click() })
    expect(container.textContent).toContain('Also clear HuggingFace cache')
  })

  it('shows a Download button for a model that needs downloading and sends requestDownloadModel with the resolved filename', () => {
    sendInit([UNDOWNLOADED_LOCAL_MODEL])
    const downloadButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Download') as HTMLButtonElement
    act(() => { downloadButton.click() })
    expect(lastMessageOfType('requestDownloadModel')).toMatchObject({ modelId: 'llama-gguf', filename: 'model.gguf' })
  })

  it('shows an error instead of downloading when the download URL has no resolvable filename', () => {
    sendInit([{ ...UNDOWNLOADED_LOCAL_MODEL, downloadUrl: 'https://huggingface.co/org/repo' }])
    const downloadButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Download') as HTMLButtonElement
    act(() => { downloadButton.click() })
    expect(postMessage.mock.calls.some(([message]) => message.type === 'requestDownloadModel')).toBe(false)
    expect(container.textContent).toContain('Edit the model and enter a specific file URL.')
  })

  it('reflects live downloadProgress events on the corresponding row', () => {
    sendInit([{ ...UNDOWNLOADED_LOCAL_MODEL, needsDownload: true }])
    const downloadButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Download') as HTMLButtonElement
    act(() => { downloadButton.click() })
    sendEvent({ type: 'downloadProgress', modelId: 'llama-gguf', progress: 0.5, status: 'downloading' })
    expect(container.textContent).toContain('50%')
  })
  it('opens the Add Model wizard overlay when the header button is clicked', () => {
    sendInit()
    const addButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('Add Model')) as HTMLButtonElement
    act(() => { addButton.click() })
    expect(container.querySelector('.custom-models-modal-overlay')).not.toBeNull()
    expect(container.querySelector('[aria-label="Add Custom Model"]')).not.toBeNull()
  })

  it('opens the edit form overlay for a specific model when its Edit button is clicked', () => {
    sendInit()
    const editButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Edit') as HTMLButtonElement
    act(() => { editButton.click() })
    expect(container.querySelector('[aria-label="Edit My Ollama"]')).not.toBeNull()
  })

  it('sends requestTestConnection for an API model and renders the result inline', () => {
    sendInit()
    const testButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Test') as HTMLButtonElement
    act(() => { testButton.click() })
    const requestId = lastMessageOfType('requestTestConnection')!.requestId
    sendEvent({ type: 'connectionTestResult', requestId, success: true, message: 'Connected successfully' })
    expect(container.textContent).toContain('Connected successfully')
  })

  it('does not show a Test Connection button for local models', () => {
    sendInit([UNDOWNLOADED_LOCAL_MODEL])
    expect(Array.from(container.querySelectorAll('button')).some((button) => button.textContent === 'Test')).toBe(false)
  })
})
