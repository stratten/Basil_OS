// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AgentTokenConnectModal, nameProblem } from './AgentTokenConnectModal'
import type { TokenConnectRequest } from '../services/tokenConnectBridge'

let container: HTMLElement
let root: Root
let onConnect: ReturnType<typeof vi.fn<(friendlyName: string, description: string | undefined, token: string) => void>>
let onCancel: ReturnType<typeof vi.fn<() => void>>

const REQUEST: TokenConnectRequest = {
  requestId: 'r1',
  serverUrl: 'https://huggingface.co/mcp',
  host: 'huggingface.co',
  friendlyName: 'Hugging Face',
  description: 'Suggested note',
  existingNames: ['Linear'],
  alreadyConnectedAs: null,
}

function setInput(label: string, value: string) {
  const input = container.querySelector(`input[aria-label="${label}"]`) as HTMLInputElement
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function render(request: TokenConnectRequest = REQUEST, isWorking = false, errorMessage: string | null = null) {
  act(() => {
    root.render(
      <AgentTokenConnectModal
        request={request}
        isWorking={isWorking}
        errorMessage={errorMessage}
        onConnect={onConnect}
        onCancel={onCancel}
      />,
    )
  })
}

describe('AgentTokenConnectModal', () => {
  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    onConnect = vi.fn<(friendlyName: string, description: string | undefined, token: string) => void>()
    onCancel = vi.fn<() => void>()
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('shows the destination host and the suggested name and description', () => {
    render()
    expect(container.textContent).toContain('huggingface.co')
    expect(container.textContent).toContain('https://huggingface.co/mcp')
    expect((container.querySelector('input[aria-label="Connection name"]') as HTMLInputElement).value).toBe('Hugging Face')
    expect((container.querySelector('input[aria-label="Connection description"]') as HTMLInputElement).value).toBe('Suggested note')
    expect((container.querySelector('button.primary-button') as HTMLButtonElement).disabled).toBe(true)
  })

  it('sends the edited name and description with the token', () => {
    render()
    act(() => {
      setInput('Connection name', '  Hugging Face (infra)  ')
      setInput('Connection description', '  Write access for model inventory  ')
      setInput('Token or API key', 'hf_abc')
    })
    act(() => {
      ;(container.querySelector('button.primary-button') as HTMLButtonElement).click()
    })
    expect(onConnect).toHaveBeenCalledWith('Hugging Face (infra)', 'Write access for model inventory', 'hf_abc')
  })

  it('treats a blank description as omitted', () => {
    render()
    act(() => {
      setInput('Connection description', '   ')
      setInput('Token or API key', 'hf_abc')
    })
    act(() => {
      ;(container.querySelector('button.primary-button') as HTMLButtonElement).click()
    })
    expect(onConnect).toHaveBeenCalledWith('Hugging Face', undefined, 'hf_abc')
  })

  it('refuses a name that is already used, including when only the case differs', () => {
    render({ ...REQUEST, existingNames: ['Hugging Face', 'Linear'], alreadyConnectedAs: 'Hugging Face' })
    expect(container.textContent).toContain('You already have Hugging Face connected')
    act(() => setInput('Token or API key', 'hf_abc'))
    expect((container.querySelector('button.primary-button') as HTMLButtonElement).disabled).toBe(true)
    expect(container.textContent).toContain('already exists')
    act(() => setInput('Connection name', 'hugging face'))
    expect((container.querySelector('button.primary-button') as HTMLButtonElement).disabled).toBe(true)
    act(() => {
      ;(container.querySelector('button.primary-button') as HTMLButtonElement).click()
    })
    expect(onConnect).not.toHaveBeenCalled()
    act(() => setInput('Connection name', 'Hugging Face (work)'))
    expect((container.querySelector('button.primary-button') as HTMLButtonElement).disabled).toBe(false)
  })

  it('Cancel does not send a token', () => {
    render()
    act(() => setInput('Token or API key', 'hf_abc'))
    act(() => {
      ;(container.querySelector('button.secondary-button') as HTMLButtonElement).click()
    })
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConnect).not.toHaveBeenCalled()
  })
})

describe('nameProblem', () => {
  it('rejects a blank, overlong, or reused name', () => {
    expect(nameProblem('   ', [])).toBe('Give this connection a name.')
    expect(nameProblem('n'.repeat(81), [])).toMatch(/80/)
    expect(nameProblem('Hugging Face', ['Hugging Face'])).toMatch(/already exists/)
    expect(nameProblem('Hugging Face (work)', ['Hugging Face'])).toBeNull()
  })
})
