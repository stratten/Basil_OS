// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SetupWindowChrome } from './SetupWindowChrome'

const postMessage = vi.fn()

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('SetupWindowChrome', () => {
  it('renders shared basil-window chrome and still posts close/minimize/collapse/expand through the Setup Assistant bridge', () => {
    window.webkit = { messageHandlers: { setupAssistant: { postMessage } } }
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root: Root = createRoot(container)

    act(() => {
      root.render(
        <SetupWindowChrome title="Basil Setup Assistant">
          <div data-testid="child">child content</div>
        </SetupWindowChrome>,
      )
    })

    expect(container.querySelector('.basil-window-title')?.textContent).toBe('Basil Setup Assistant')
    expect(container.querySelector('.basil-window-header')).not.toBeNull()
    expect(container.querySelector('.basil-window-surface')).not.toBeNull()
    expect(container.querySelector('.basil-window-content')).not.toBeNull()
    expect(container.querySelector('[data-testid="child"]')?.textContent).toBe('child content')

    const closeButton = container.querySelector<HTMLButtonElement>('button[aria-label="Close window"]')!
    const minimizeButton = container.querySelector<HTMLButtonElement>('button[aria-label="Minimize window"]')!
    const collapseButton = container.querySelector<HTMLButtonElement>('button[aria-label="Collapse window"]')!

    act(() => {
      closeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ name: 'closeSetupAssistant' }))

    act(() => {
      minimizeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ name: 'minimizeSetupAssistant' }))

    act(() => {
      collapseButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ name: 'collapseSetupAssistant' }))

    const expandButton = container.querySelector<HTMLButtonElement>('button[aria-label="Expand window"]')!
    act(() => {
      expandButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ name: 'expandSetupAssistant' }))

    act(() => {
      root.unmount()
    })
    container.remove()
  })
})
