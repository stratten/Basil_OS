// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AddLocalServerModal } from './AddLocalServerModal'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: ReturnType<typeof vi.fn<(id: string) => void>>
let onBack: ReturnType<typeof vi.fn<() => void>>
let onDismiss: ReturnType<typeof vi.fn<() => void>>

type Props = { pendingId: string | null; requestError: string | null }

function render(props: Partial<Props> = {}) {
  act(() => {
    root.render(
      <AddLocalServerModal
        pendingId={props.pendingId ?? null}
        requestError={props.requestError ?? null}
        onTrackRequest={onTrackRequest}
        onBack={onBack}
        onDismiss={onDismiss}
      />,
    )
  })
}

function field(name: string): HTMLInputElement | HTMLTextAreaElement {
  const element = container.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[name="${name}"]`)
  if (!element) throw new Error(`No field named ${name}`)
  return element
}

function setValue(name: string, value: string) {
  const element = field(name)
  const prototype = element instanceof window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value)
  element.dispatchEvent(new Event('input', { bubbles: true }))
}

function submit() {
  act(() => { container.querySelector<HTMLButtonElement>('.connections-add-form-actions .primary-button')!.click() })
}

function fillBasics() {
  act(() => {
    setValue('name', 'WhatsApp')
    setValue('command', '/usr/local/bin/uv')
    setValue('args', 'run\nmain.py')
    setValue('env', 'MODE=local')
    setValue('secretNames', 'API_KEY')
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  onTrackRequest = vi.fn<(id: string) => void>()
  onBack = vi.fn<() => void>()
  onDismiss = vi.fn<() => void>()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('AddLocalServerModal', () => {
  it('warns that the program runs with full access and offers Back', () => {
    render()
    expect(container.querySelector('.connections-local-warning')?.textContent).toContain('full access to your files and network')
    act(() => { Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === 'Back')!.click() })
    expect(onBack).toHaveBeenCalled()
  })

  it('says what is wrong and sends nothing when the form is incomplete', () => {
    render()
    submit()
    expect(container.querySelector('.connections-local-error')?.textContent).toBe('Enter a name for the server.')
    expect(postMessage).not.toHaveBeenCalled()
    expect(onTrackRequest).not.toHaveBeenCalled()
  })

  it('shows one password field per secret name and refuses to add until each has a value', () => {
    render()
    fillBasics()
    expect(container.querySelectorAll('input[type="password"]')).toHaveLength(1)
    expect(field('secret-API_KEY').getAttribute('type')).toBe('password')
    submit()
    expect(container.querySelector('.connections-local-error')?.textContent).toBe('Enter a value for API_KEY.')
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('sends the definition and the trimmed secret values in one message and tracks the request', () => {
    render()
    fillBasics()
    act(() => { setValue('secret-API_KEY', '  super-secret-value  ') })
    submit()

    expect(postMessage).toHaveBeenCalledTimes(1)
    const message = postMessage.mock.calls[0][0]
    expect(message).toMatchObject({
      type: 'requestRegisterLocalServer',
      registration: {
        friendlyName: 'WhatsApp',
        command: '/usr/local/bin/uv',
        args: ['run', 'main.py'],
        env: { MODE: 'local' },
        secretEnv: ['API_KEY'],
        companion: null,
      },
      secretValues: { API_KEY: 'super-secret-value' },
    })
    expect(JSON.stringify(message.registration)).not.toContain('super-secret-value')
    expect(onTrackRequest).toHaveBeenCalledWith(message.requestId)
  })

  it('never shows a secret value as text', () => {
    render()
    fillBasics()
    act(() => { setValue('secret-API_KEY', 'super-secret-value') })
    expect(container.textContent).not.toContain('super-secret-value')
    expect(field('secret-API_KEY').getAttribute('type')).toBe('password')
  })

  it('adds the background program fields, lists a shared secret once, and sends its settings', () => {
    render()
    act(() => {
      setValue('name', 'Bridge')
      setValue('command', '/usr/bin/env')
      setValue('args', '--port={port}')
      setValue('secretNames', 'SHARED')
    })
    expect(container.querySelector('[name="companionCommand"]')).toBeNull()
    act(() => { field('useCompanion').click() })
    act(() => {
      setValue('companionCommand', '/usr/local/bin/go')
      setValue('companionArgs', 'run\n.\n{port}')
      setValue('companionSecretNames', 'SHARED BRIDGE_TOKEN')
      setValue('fixedPort', '')
    })
    expect(container.querySelectorAll('input[type="password"]')).toHaveLength(2)
    act(() => {
      setValue('secret-SHARED', 's-1')
      setValue('secret-BRIDGE_TOKEN', 's-2')
    })
    act(() => { field('startWithBasil').click() })
    submit()

    const message = postMessage.mock.calls[0][0]
    expect(message.registration.companion).toMatchObject({
      command: '/usr/local/bin/go',
      args: ['run', '.', '{port}'],
      secretEnv: ['SHARED', 'BRIDGE_TOKEN'],
      startWithBasil: false,
    })
    expect(message.secretValues).toEqual({ SHARED: 's-1', 'BRIDGE_TOKEN': 's-2' })
    expect(container.querySelector('.connections-local-section .connections-local-hint')?.textContent).toContain('{port}')
  })

  it('shows a waiting message while the request runs and closes once it finishes without an error', () => {
    render()
    fillBasics()
    act(() => { setValue('secret-API_KEY', 'k') })
    submit()
    const requestId = onTrackRequest.mock.calls[0][0]

    render({ pendingId: requestId })
    expect(container.querySelector('.connections-local-progress')?.textContent).toContain('up to a minute')
    expect(Array.from(container.querySelectorAll<HTMLButtonElement>('button')).every((button) => button.disabled)).toBe(true)
    expect(onDismiss).not.toHaveBeenCalled()

    render({ pendingId: null, requestError: null })
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('stays open with the form intact and the error shown when the request fails, and can be retried', () => {
    render()
    fillBasics()
    act(() => { setValue('secret-API_KEY', 'k') })
    submit()
    const requestId = onTrackRequest.mock.calls[0][0]

    render({ pendingId: requestId })
    render({ pendingId: null, requestError: 'WhatsApp was not added, because it did not start.' })

    expect(onDismiss).not.toHaveBeenCalled()
    expect(container.querySelector('.connections-local-error')?.textContent).toBe('WhatsApp was not added, because it did not start.')
    expect(field('name').value).toBe('WhatsApp')
    expect(field('secret-API_KEY').value).toBe('k')
    submit()
    expect(postMessage).toHaveBeenCalledTimes(2)
  })
})

describe('AddLocalServerModal close control', () => {
  const closeButton = () => container.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => { root.unmount() })
    container.remove()
  })

  it('has a close button at the top left of the header that dismisses the whole modal, not just this step', () => {
    render()

    expect(container.querySelector('.basil-modal-header')!.firstElementChild).toBe(closeButton())
    act(() => closeButton().click())

    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('disables the close button while a request is pending', () => {
    render({ pendingId: 'adding-1' })

    expect(closeButton().disabled).toBe(true)
  })
})
