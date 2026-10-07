// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CustomModelWizard } from './CustomModelWizard'
import type { LatestBridgeEvent } from '../CustomModelsPanel'

vi.mock('../../services/customModelsBridge', () => ({
  requestCreateModel: vi.fn(),
  requestDownloadModel: vi.fn(),
  requestFetchGGUFMetadata: vi.fn(),
  requestFetchLocalGGUFMetadata: vi.fn(),
  requestPickLocalFile: vi.fn(),
  requestProbeHFRepo: vi.fn(),
  requestTestConnection: vi.fn(),
}))

import {
  requestCreateModel, requestDownloadModel, requestFetchGGUFMetadata, requestProbeHFRepo,
} from '../../services/customModelsBridge'

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

function render(latestEvent: LatestBridgeEvent | null) {
  act(() => { root.render(<CustomModelWizard latestEvent={latestEvent} onDismiss={onDismiss} />) })
}

function findButton(text: string): HTMLButtonElement {
  return Array.from(container.querySelectorAll('button')).find((button) => {
    if (button.textContent === text) return true
    const title = button.querySelector('.custom-models-selection-card-title')?.textContent
    return title === text
  }) as HTMLButtonElement
}

function findFieldInput(labelText: string): HTMLInputElement {
  const field = Array.from(container.querySelectorAll('.custom-models-form-field')).find(
    (element) => element.querySelector('.custom-models-form-field-label')?.textContent === labelText
  )
  return field?.querySelector('input') as HTMLInputElement
}

beforeEach(() => {
  vi.clearAllMocks()
  onDismiss = vi.fn()
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  render(null)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('CustomModelWizard', () => {
  it('takes the API path straight to Details and sends requestCreateModel with API-specific fields on Save', () => {
    act(() => { findButton('API / Remote Model').click() })
    expect(container.textContent).toContain('Model Details')

    typeInto(findFieldInput('Display Name'), 'My API Model')
    typeInto(findFieldInput('Base URL'), 'http://localhost:11434/v1')
    typeInto(findFieldInput('Model Identifier'), 'llama3.3')

    ;(requestCreateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('create-1')
    act(() => { findButton('Add Model').click() })

    expect(requestCreateModel).toHaveBeenCalledWith(expect.objectContaining({
      displayName: 'My API Model', handler: 'openai_compatible', baseUrl: 'http://localhost:11434/v1',
      modelIdentifier: 'llama3.3', requiresAuth: false, apiKey: undefined, modelPath: undefined, downloadUrl: undefined,
      serverType: 'openai_compatible',
    }))

    render({ seq: 1, event: { type: 'intentResult', requestId: 'create-1', status: 'success' } })
    expect(onDismiss).toHaveBeenCalled()
  })

  it('sends the Ollama server type when the user selects it for an API model', () => {
    act(() => { findButton('API / Remote Model').click() })
    typeInto(findFieldInput('Display Name'), 'Ollama Model')
    typeInto(findFieldInput('Base URL'), 'http://localhost:11434/v1')
    typeInto(findFieldInput('Model Identifier'), 'qwen2.5:1.5b')
    const serverTypeSelect = container.querySelector<HTMLButtonElement>('[aria-label="Server Type"]')!
    act(() => { serverTypeSelect.click() })
    const ollamaOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Ollama')!
    act(() => { ollamaOption.click() })
    ;(requestCreateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('create-ollama')
    act(() => { findButton('Add Model').click() })
    expect(requestCreateModel).toHaveBeenCalledWith(expect.objectContaining({ handler: 'openai_compatible', serverType: 'ollama' }))
  })

  it('shows a save error and does not dismiss when creation fails', () => {
    act(() => { findButton('API / Remote Model').click() })
    typeInto(findFieldInput('Display Name'), 'Broken Model')
    typeInto(findFieldInput('Base URL'), 'http://localhost:11434/v1')
    typeInto(findFieldInput('Model Identifier'), 'llama3.3')
    ;(requestCreateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('create-2')
    act(() => { findButton('Add Model').click() })
    render({ seq: 1, event: { type: 'intentResult', requestId: 'create-2', status: 'error', message: 'modelId already exists' } })
    expect(onDismiss).not.toHaveBeenCalled()
    expect(container.textContent).toContain('modelId already exists')
  })

  it('does not allow fractional context limits to be submitted', () => {
    act(() => { findButton('API / Remote Model').click() })
    typeInto(findFieldInput('Display Name'), 'Fractional Model')
    typeInto(findFieldInput('Base URL'), 'http://localhost:11434/v1')
    typeInto(findFieldInput('Model Identifier'), 'llama3.3')
    typeInto(findFieldInput('Context Window (tokens)'), '4096.5')
    expect(findButton('Add Model').disabled).toBe(true)
  })

  it('walks the local HuggingFace path through probe, file selection, auto-advance, create, and auto-download', () => {
    act(() => { findButton('Local Model').click() })
    expect(container.textContent).toContain('Where is your model located?')

    act(() => { findButton('Download from HuggingFace').click() })
    expect(container.textContent).toContain('HuggingFace Repository')

    typeInto(container.querySelector('#custom-models-hf-url') as HTMLInputElement, 'TheBloke/Llama-2-7B-GGUF')
    ;(requestProbeHFRepo as unknown as ReturnType<typeof vi.fn>).mockReturnValue('probe-1')
    act(() => { findButton('Search').click() })
    expect(requestProbeHFRepo).toHaveBeenCalledWith('TheBloke/Llama-2-7B-GGUF')

    render({
      seq: 1,
      event: {
        type: 'hfProbeResult', requestId: 'probe-1', repoId: 'TheBloke/Llama-2-7B-GGUF',
        ggufFiles: [{ name: 'llama-2-7b.Q4_K_M.gguf', sizeBytes: 4_000_000_000, sizeHuman: '4.0 GB' }],
        modelMetadata: null, error: null,
      },
    })
    expect(container.textContent).toContain('llama-2-7b.Q4_K_M.gguf')

    ;(requestFetchGGUFMetadata as unknown as ReturnType<typeof vi.fn>).mockReturnValue('meta-1')
    const fileRadio = container.querySelector('input[type="radio"][name="hf-gguf-file"]') as HTMLInputElement
    act(() => { fileRadio.click() })
    expect(requestFetchGGUFMetadata).toHaveBeenCalledWith('TheBloke/Llama-2-7B-GGUF', 'llama-2-7b.Q4_K_M.gguf')

    render({
      seq: 2,
      event: {
        type: 'ggufMetadataResult', requestId: 'meta-1', success: true,
        contextWindow: 4096, architecture: 'llama', modelName: 'Llama 2 7B', error: null,
      },
    })
    expect(container.textContent).toContain('Model Details')
    expect(findFieldInput('Display Name').value).toBe('Llama 2 7B')
    expect(findFieldInput('Model ID').value).toBe('llama-2-7b')

    ;(requestCreateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('create-3')
    act(() => { findButton('Add Model').click() })
    expect(requestCreateModel).toHaveBeenCalledWith(expect.objectContaining({
      handler: 'llama_cpp', downloadUrl: 'https://huggingface.co/TheBloke/Llama-2-7B-GGUF/resolve/main/llama-2-7b.Q4_K_M.gguf', modelPath: undefined,
      baseUrl: undefined, modelIdentifier: undefined, requiresAuth: false, fileSize: 4_000_000_000, fileSizeHuman: '4.0 GB',
    }))

    ;(requestDownloadModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('download-3')
    render({ seq: 3, event: { type: 'intentResult', requestId: 'create-3', status: 'success' } })
    expect(requestDownloadModel).toHaveBeenCalledWith('llama-2-7b', 'llama-2-7b.Q4_K_M.gguf')
    expect(onDismiss).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Downloading')

    render({ seq: 4, event: { type: 'intentResult', requestId: 'download-3', status: 'success' } })
    expect(onDismiss).toHaveBeenCalled()
  })

  it('shows a retry-from-list error when the model is created but the auto-download fails', () => {
    act(() => { findButton('Local Model').click() })
    act(() => { findButton('Download from HuggingFace').click() })
    typeInto(container.querySelector('#custom-models-hf-url') as HTMLInputElement, 'org/repo')
    ;(requestProbeHFRepo as unknown as ReturnType<typeof vi.fn>).mockReturnValue('probe-2')
    act(() => { findButton('Search').click() })
    render({
      seq: 1,
      event: { type: 'hfProbeResult', requestId: 'probe-2', repoId: 'org/repo', ggufFiles: [{ name: 'model.gguf', sizeBytes: null, sizeHuman: null }], modelMetadata: null, error: null },
    })
    ;(requestFetchGGUFMetadata as unknown as ReturnType<typeof vi.fn>).mockReturnValue('meta-2')
    act(() => { (container.querySelector('input[type="radio"][name="hf-gguf-file"]') as HTMLInputElement).click() })
    render({ seq: 2, event: { type: 'ggufMetadataResult', requestId: 'meta-2', success: true, contextWindow: 2048, architecture: null, modelName: 'Repo Model', error: null } })
    ;(requestCreateModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('create-4')
    act(() => { findButton('Add Model').click() })
    ;(requestDownloadModel as unknown as ReturnType<typeof vi.fn>).mockReturnValue('download-4')
    render({ seq: 3, event: { type: 'intentResult', requestId: 'create-4', status: 'success' } })
    render({ seq: 4, event: { type: 'intentResult', requestId: 'download-4', status: 'error', message: 'Connection timed out' } })
    expect(onDismiss).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Model was created but download failed: Connection timed out')
  })
})
