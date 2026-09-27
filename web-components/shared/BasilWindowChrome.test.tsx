// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { BasilWindowChrome } from './BasilWindowChrome'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('BasilWindowChrome', () => {
  it('renders the title, child content, and accessible close/minimize/collapse controls without payloads', () => {
    const onClose = vi.fn()
    const onMinimize = vi.fn()
    const onCollapse = vi.fn()
    const onExpand = vi.fn()
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root: Root = createRoot(container)

    act(() => {
      root.render(
        <BasilWindowChrome title="Appearance" onClose={onClose} onMinimize={onMinimize} onCollapse={onCollapse} onExpand={onExpand}>
          <div data-testid="child">child content</div>
        </BasilWindowChrome>,
      )
    })

    expect(container.querySelector('[data-testid="child"]')?.textContent).toBe('child content')
    expect(container.querySelector('.basil-window-title')?.textContent).toBe('Appearance')

    const closeButton = container.querySelector<HTMLButtonElement>('button[aria-label="Close window"]')!
    const minimizeButton = container.querySelector<HTMLButtonElement>('button[aria-label="Minimize window"]')!

    act(() => {
      closeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith()

    act(() => {
      minimizeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onMinimize).toHaveBeenCalledTimes(1)
    expect(onMinimize).toHaveBeenCalledWith()

    act(() => {
      root.unmount()
    })
    container.remove()
  })

  it('toggles the collapse control, notifies the bridge, and hides content while collapsed', () => {
    const onCollapse = vi.fn()
    const onExpand = vi.fn()
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root: Root = createRoot(container)

    act(() => {
      root.render(
        <BasilWindowChrome title="Appearance" onClose={vi.fn()} onMinimize={vi.fn()} onCollapse={onCollapse} onExpand={onExpand}>
          <div data-testid="child">child content</div>
        </BasilWindowChrome>,
      )
    })

    const collapseButton = container.querySelector<HTMLButtonElement>('button[aria-label="Collapse window"]')!
    const content = container.querySelector('.basil-window-content')!

    act(() => {
      collapseButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onCollapse).toHaveBeenCalledTimes(1)
    expect(content.classList.contains('is-collapsed')).toBe(true)
    expect(content.getAttribute('aria-hidden')).toBe('true')

    const expandButton = container.querySelector<HTMLButtonElement>('button[aria-label="Expand window"]')!
    act(() => {
      expandButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onExpand).toHaveBeenCalledTimes(1)
    expect(content.classList.contains('is-collapsed')).toBe(false)

    act(() => {
      root.unmount()
    })
    container.remove()
  })
})
