// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ModalHeader } from './ModalHeader'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

function render(props: Partial<Parameters<typeof ModalHeader>[0]> = {}) {
  const onClose = vi.fn()
  act(() => {
    root.render(<ModalHeader title="Add Connection" onClose={onClose} {...props} />)
  })
  return onClose
}

const closeButton = () => container.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!

function pressEscape(options: { prevent?: boolean } = {}) {
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  if (options.prevent) event.preventDefault()
  act(() => {
    document.body.dispatchEvent(event)
  })
}

describe('ModalHeader', () => {
  it('puts the close button first, ahead of the title, the way a Basil window header does', () => {
    render()

    const header = container.querySelector('header')!
    expect(header.firstElementChild).toBe(closeButton())
    expect(header.lastElementChild?.tagName).toBe('H3')
    expect(header.lastElementChild?.textContent).toBe('Add Connection')
  })

  it('draws the shared window-control close glyph', () => {
    render()

    expect(closeButton().querySelector('.basil-window-control-circle')).not.toBeNull()
    expect(closeButton().querySelectorAll('line')).toHaveLength(2)
  })

  it('closes from the close button', () => {
    const onClose = render()

    act(() => closeButton().click())

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on Escape, once, and not when something else already handled the key', () => {
    const onClose = render()

    pressEscape()
    expect(onClose).toHaveBeenCalledTimes(1)

    pressEscape({ prevent: true })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('ignores Escape when the host handles it itself', () => {
    const onClose = render({ closeOnEscape: false })

    pressEscape()

    expect(onClose).not.toHaveBeenCalled()
  })

  it('does nothing while the dialog is busy: the button is disabled and Escape is ignored', () => {
    const onClose = render({ closeDisabled: true })

    expect(closeButton().disabled).toBe(true)
    act(() => closeButton().click())
    pressEscape()

    expect(onClose).not.toHaveBeenCalled()
  })

  it('stops listening for Escape once it unmounts', () => {
    const onClose = render()

    act(() => root.render(<div />))
    pressEscape()

    expect(onClose).not.toHaveBeenCalled()
  })

  it('passes the title id and the host title class through', () => {
    render({ titleId: 'dialog-title', titleClassName: 'host-title' })

    const title = container.querySelector('h3')!
    expect(title.id).toBe('dialog-title')
    expect(title.className).toBe('host-title')
  })

  it('names the close button for assistive technology and accepts a different label', () => {
    render({ closeLabel: 'Close image' })

    expect(container.querySelector('button[aria-label="Close image"]')).not.toBeNull()
  })
})
