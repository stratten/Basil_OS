// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BasilModalDialog } from './BasilModalDialog'

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
  document.querySelectorAll('.basil-webkit-window-surface').forEach(node => node.remove())
})

function renderDialog(onClose = vi.fn()) {
  act(() => {
    root.render(
      <BasilModalDialog title="Sign in to use Basil Cloud" onClose={onClose} testId="modal">
        <button type="button">Inside</button>
      </BasilModalDialog>,
    )
  })
  return onClose
}

describe('BasilModalDialog', () => {
  it('is a labeled modal dialog with the title and content inside the shared card', () => {
    renderDialog()

    const dialog = document.querySelector('[role="dialog"]')!
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.classList.contains('basil-modal-dialog')).toBe(true)
    expect(document.getElementById(dialog.getAttribute('aria-labelledby')!)?.textContent).toBe('Sign in to use Basil Cloud')
    expect(dialog.textContent).toContain('Inside')
    expect(document.activeElement).toBe(dialog)
  })

  it('draws inside the Basil window surface when there is one, so the backdrop takes the window clip', () => {
    const surface = document.createElement('div')
    surface.className = 'basil-webkit-window-surface'
    document.body.appendChild(surface)

    renderDialog()

    expect(surface.querySelector('[data-testid="modal"]')?.classList.contains('basil-modal-backdrop')).toBe(true)
    expect(container.querySelector('[data-testid="modal"]')).toBeNull()
  })

  it('falls back to the document body outside a Basil window', () => {
    renderDialog()

    expect(document.body.querySelector(':scope > [data-testid="modal"]')).not.toBeNull()
  })

  it('closes on Escape and on a backdrop press, but not on a press inside the card', () => {
    const onClose = renderDialog()

    act(() => { document.querySelector('.basil-modal-dialog')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    expect(onClose).not.toHaveBeenCalled()

    act(() => { document.querySelector('[data-testid="modal"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    expect(onClose).toHaveBeenCalledTimes(1)

    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(onClose).toHaveBeenCalledTimes(2)
  })
  it('ignores Escape and a backdrop press when it is not dismissible, so work and decisions end only through its own buttons', () => {
    const onClose = vi.fn()
    act(() => {
      root.render(
        <BasilModalDialog title="Working" onClose={onClose} testId="modal" dismissible={false}>
          <button type="button">Cancel</button>
        </BasilModalDialog>,
      )
    })

    act(() => { document.querySelector('[data-testid="modal"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })

    expect(onClose).not.toHaveBeenCalled()
  })

  it('has a close button at the top left of the card, ahead of the title, outside the scrolling body, and it calls onClose once', () => {
    const onClose = renderDialog()

    const dialog = document.querySelector('.basil-modal-dialog')!
    const close = dialog.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!
    expect(dialog.firstElementChild?.firstElementChild).toBe(close)
    expect(dialog.querySelector('.basil-modal-body')!.contains(close)).toBe(false)

    act(() => close.click())

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('draws no close button when it is not dismissible and names no close action, rather than a dead one', () => {
    act(() => {
      root.render(
        <BasilModalDialog title="Working" onClose={vi.fn()} testId="modal" dismissible={false}>
          <p>Body</p>
        </BasilModalDialog>,
      )
    })

    expect(document.querySelector('button[aria-label="Close"]')).toBeNull()
    expect(document.querySelector('.basil-modal-header h3')?.textContent).toBe('Working')
  })

  it('gives a non-dismissible dialog a close button that takes its own close action, while Escape and the backdrop stay inert', () => {
    const onClose = vi.fn()
    const onCloseAction = vi.fn()
    act(() => {
      root.render(
        <BasilModalDialog title="Review" onClose={onClose} testId="modal" dismissible={false} closeAction={{ onClick: onCloseAction }}>
          <p>Body</p>
        </BasilModalDialog>,
      )
    })

    act(() => { document.querySelector('[data-testid="modal"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(onCloseAction).not.toHaveBeenCalled()

    act(() => document.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!.click())

    expect(onCloseAction).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('disables that close button while its action is unavailable', () => {
    const onCloseAction = vi.fn()
    act(() => {
      root.render(
        <BasilModalDialog title="Saving" onClose={vi.fn()} testId="modal" dismissible={false} closeAction={{ onClick: onCloseAction, disabled: true }}>
          <p>Body</p>
        </BasilModalDialog>,
      )
    })

    const close = document.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!
    expect(close.disabled).toBe(true)
    act(() => close.click())

    expect(onCloseAction).not.toHaveBeenCalled()
  })

  it('closes once, not twice, when Escape is pressed, because the header leaves Escape to the dialog', () => {
    const onClose = renderDialog()

    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('uses the wide card on request and fixes the backdrop to the viewport only when it falls back to the body', () => {
    act(() => {
      root.render(<BasilModalDialog title="Review" onClose={vi.fn()} testId="modal" size="wide"><p>Body</p></BasilModalDialog>)
    })

    expect(document.querySelector('.basil-modal-dialog')!.classList.contains('basil-modal-dialog--wide')).toBe(true)
    expect(document.querySelector('[data-testid="modal"]')!.classList.contains('basil-modal-backdrop--viewport')).toBe(true)
  })

  it('leaves the backdrop absolutely positioned inside a Basil window surface', () => {
    const surface = document.createElement('div')
    surface.className = 'basil-webkit-window-surface'
    document.body.appendChild(surface)

    renderDialog()

    expect(surface.querySelector('[data-testid="modal"]')!.classList.contains('basil-modal-backdrop--viewport')).toBe(false)
  })
})
