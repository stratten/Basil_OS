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
