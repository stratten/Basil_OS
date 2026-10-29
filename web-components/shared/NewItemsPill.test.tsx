// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import NewItemsPill from './NewItemsPill'

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

describe('NewItemsPill', () => {
  it('renders nothing when there are no new items', () => {
    act(() => root.render(<NewItemsPill count={0} onClick={vi.fn()} />))
    expect(container.children).toHaveLength(0)
  })

  it('shows the count with a plural-aware accessible name and reports clicks', () => {
    const onClick = vi.fn()
    act(() => root.render(<NewItemsPill count={1} onClick={onClick} />))
    const button = container.querySelector('button')!
    expect(button.getAttribute('aria-label')).toBe('Jump to 1 new item')
    expect(button.textContent).toContain('1 new')

    act(() => root.render(<NewItemsPill count={3} onClick={onClick} />))
    const updated = container.querySelector('button')!
    expect(updated.getAttribute('aria-label')).toBe('Jump to 3 new items')
    act(() => updated.dispatchEvent(new MouseEvent('click', { bubbles: true })))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
