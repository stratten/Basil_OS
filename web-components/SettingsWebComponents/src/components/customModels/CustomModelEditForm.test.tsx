// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CustomModelEditForm } from './CustomModelEditForm'
import type { LatestBridgeEvent } from '../CustomModelsPanel'
import type { CustomModelSummary } from '../../types'

vi.mock('../../services/customModelsBridge', () => ({
  requestFetchLocalGGUFMetadata: vi.fn(),
  requestPickLocalFile: vi.fn(),
  requestTestConnection: vi.fn(),
  requestUpdateModel: vi.fn(),
}))

import { requestFetchLocalGGUFMetadata, requestPickLocalFile, requestUpdateModel } from '../../services/customModelsBridge'

const API_MODEL: CustomModelSummary = {
  modelId: 'my-ollama', displayName: 'My Ollama', handler: 'openai_compatible', isLocal: false,
  baseUrl: 'http://localhost:11434/v1', modelIdentifier: 'llama3.3', modelPath: null, downloadUrl: null,
  contextWindow: 8192, maxOutputTokens: 4096, requiresAuth: false, capabilities: ['reasoning'],
  features: ['streaming', 'system_prompts'], toolRendering: null, toolCallFormat: null, serverType: null, description: null,
  fileSize: null, fileSizeHuman: null, needsDownload: false,
}

const LOCAL_FILE_MODEL: CustomModelSummary = {
  modelId: 'llama-gguf', displayName: 'Llama GGUF', handler: 'llama_cpp', isLocal: true,
  baseUrl: null, modelIdentifier: null, modelPath: '/Users/test/model.gguf', downloadUrl: null,
  contextWindow: 4096, maxOutputTokens: 2048, requiresAuth: false, capabilities: ['reasoning'],
  features: [], toolRendering: null, toolCallFormat: null, serverType: null, description: null,
  fileSize: 4_000_000_000, fileSizeHuman: '4.0 GB', needsDownload: false,
}

let container: HTMLElement
let root: Root
let onDismiss: () => void

function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  act(() => {
    setter?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function findFieldInput(labelText: string): HTMLInputElement {
  const field = Array.from(container.querySelectorAll('.custom-models-form-field')).find(
    (element) => element.querySelector('.custom-models-form-field-label')?.textContent === labelText
  )
  return field?.querySelector('input') as HTMLInputElement
}

function findButton(text: string): HTMLButtonElement {
  return Array.from(container.querySelectorAll('button')).find((button) => button.textContent === text) as HTMLButtonElement
}

function render(model: CustomModelSummary, latestEvent: LatestBridgeEvent | null) {
  act(() => { root.render(<CustomModelEditForm model={model} latestEvent={latestEvent} onDismiss={onDismiss} />) })
}

beforeEach(() => {
  vi.clearAllMocks()
  onDismiss = vi.fn()
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('CustomModelEditForm', () => {
  it('pre-populates fields from the existing API model and never pre-fills the API key', () => {
    render(API_MODEL, null)
    expect(findFieldInput('Display Name').value).toBe('My Ollama')
    expect(findFieldInput('Base URL').value).toBe('http://localhost:11434/v1')
    const apiKeyField = container.querySelector('input[type="password"]')
    expect(apiKeyField).toBeNull()
  })

  it('sends requestUpdateModel with edited fields and omits apiKey when left blank', () => {
    render(API_MODEL, null)
    typeInto(findFieldInput('Display Name'), 'Renamed Ollama')
    ;(requestUpdateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('update-1')
    act(() => { findButton('Save Changes').click() })
    expect(requestUpdateModel).toHaveBeenCalledWith('my-ollama', expect.objectContaining({
      displayName: 'Renamed Ollama', handler: 'openai_compatible', baseUrl: 'http://localhost:11434/v1', modelIdentifier: 'llama3.3', apiKey: undefined,
    }))
  })

  it('allows a remote model to switch API handlers before saving', () => {
    render(API_MODEL, null)
    const handlerSelect = container.querySelector<HTMLButtonElement>('[aria-label="API Handler"]')!
    act(() => { handlerSelect.click() })
    const anthropicOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Anthropic-Compatible')!
    act(() => { anthropicOption.click() })
    ;(requestUpdateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('update-handler')
    act(() => { findButton('Save Changes').click() })
    expect(requestUpdateModel).toHaveBeenCalledWith('my-ollama', expect.objectContaining({
      handler: 'anthropic_compatible',
    }))
  })

  it('defaults the server type to other OpenAI-compatible servers and saves an Ollama selection', () => {
    render(API_MODEL, null)
    const serverTypeSelect = container.querySelector<HTMLButtonElement>('[aria-label="Server Type"]')!
    expect(serverTypeSelect.textContent).toContain('Other OpenAI-compatible server')
    act(() => { serverTypeSelect.click() })
    const ollamaOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Ollama')!
    act(() => { ollamaOption.click() })
    ;(requestUpdateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('update-server-type')
    act(() => { findButton('Save Changes').click() })
    expect(requestUpdateModel).toHaveBeenCalledWith('my-ollama', expect.objectContaining({ serverType: 'ollama' }))
  })

  it('pre-selects a saved Ollama server type and hides it for Anthropic-compatible handlers', () => {
    render({ ...API_MODEL, serverType: 'ollama' }, null)
    expect(container.querySelector('[aria-label="Server Type"]')!.textContent).toContain('Ollama')
    const handlerSelect = container.querySelector<HTMLButtonElement>('[aria-label="API Handler"]')!
    act(() => { handlerSelect.click() })
    const anthropicOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Anthropic-Compatible')!
    act(() => { anthropicOption.click() })
    expect(container.querySelector('[aria-label="Server Type"]')).toBeNull()
    ;(requestUpdateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('update-anthropic')
    act(() => { findButton('Save Changes').click() })
    expect(requestUpdateModel).toHaveBeenCalledWith('my-ollama', expect.objectContaining({ handler: 'anthropic_compatible', serverType: undefined }))
  })

  it('does not allow fractional context limits to be saved', () => {
    render(API_MODEL, null)
    typeInto(findFieldInput('Context Window (tokens)'), '8192.5')
    expect(findButton('Save Changes').disabled).toBe(true)
  })

  it('dismisses on a successful save and shows an error on a failed save', () => {
    render(API_MODEL, null)
    ;(requestUpdateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('update-2')
    act(() => { findButton('Save Changes').click() })
    render(API_MODEL, { seq: 1, event: { type: 'intentResult', requestId: 'update-2', status: 'error', message: 'Endpoint unreachable' } })
    expect(onDismiss).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Endpoint unreachable')

    ;(requestUpdateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('update-3')
    act(() => { findButton('Save Changes').click() })
    render(API_MODEL, { seq: 2, event: { type: 'intentResult', requestId: 'update-3', status: 'success' } })
    expect(onDismiss).toHaveBeenCalled()
  })

  it('lets a local-file-sourced model browse for a different file and submits the new modelPath', () => {
    render(LOCAL_FILE_MODEL, null)
    expect(container.textContent).toContain('/Users/test/model.gguf')
    ;(requestPickLocalFile as unknown as ReturnType<typeof vi.fn>).mockReturnValue('pick-1')
    ;(requestFetchLocalGGUFMetadata as unknown as ReturnType<typeof vi.fn>).mockReturnValue('metadata-1')
    act(() => { findButton('Choose a Different File...').click() })
    render(LOCAL_FILE_MODEL, { seq: 1, event: { type: 'localFilePicked', requestId: 'pick-1', path: '/Users/test/model-v2.gguf' } })
    expect(container.textContent).toContain('/Users/test/model-v2.gguf')
    expect(requestFetchLocalGGUFMetadata).toHaveBeenCalledWith('/Users/test/model-v2.gguf')

    render(LOCAL_FILE_MODEL, { seq: 2, event: { type: 'ggufMetadataResult', requestId: 'unrelated', success: true, contextWindow: 8192, architecture: null, modelName: null, error: null } })
    expect(findFieldInput('Context Window (tokens)').value).toBe('4096')

    render(LOCAL_FILE_MODEL, { seq: 3, event: { type: 'ggufMetadataResult', requestId: 'metadata-1', success: true, contextWindow: 8192, architecture: null, modelName: null, error: null } })
    expect(findFieldInput('Context Window (tokens)').value).toBe('8192')

    ;(requestUpdateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('update-4')
    act(() => { findButton('Save Changes').click() })
    expect(requestUpdateModel).toHaveBeenCalledWith('llama-gguf', expect.objectContaining({ modelPath: '/Users/test/model-v2.gguf' }))
  })

  it('does not render an Authentication or Connection Test section for local models', () => {
    render(LOCAL_FILE_MODEL, null)
    expect(container.textContent).not.toContain('Test Connection')
    expect(container.textContent).not.toContain('Requires API Key')
  })
})
