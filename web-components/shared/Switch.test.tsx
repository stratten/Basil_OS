// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Switch } from './Switch'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  window.getSelection()?.removeAllRanges()
  act(() => root.unmount())
  container.remove()
})

function selectLabelText() {
  const label = container.querySelector('label')!
  const range = document.createRange()
  range.selectNodeContents(label)
  const selection = window.getSelection()!
  selection.removeAllRanges()
  selection.addRange(range)
}

describe('Switch', () => {
  it('toggles on a plain click of the label text', () => {
    const onChange = vi.fn()
    act(() => root.render(<Switch checked={false} onChange={onChange} label="Use API models" />))

    act(() => { container.querySelector('label')!.click() })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('toggles on a click of the switch itself', () => {
    const onChange = vi.fn()
    act(() => root.render(<Switch checked={false} onChange={onChange} label="Use API models" />))

    act(() => { container.querySelector('input')!.click() })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('does not toggle when the click ends a text selection inside the label', () => {
    const onChange = vi.fn()
    act(() => root.render(<Switch checked={false} onChange={onChange} label="Use API models" />))
    selectLabelText()

    act(() => { container.querySelector('label')!.click() })

    expect(onChange).not.toHaveBeenCalled()
  })

  it('still toggles from the switch itself while text is selected', () => {
    const onChange = vi.fn()
    act(() => root.render(<Switch checked={false} onChange={onChange} label="Use API models" />))
    selectLabelText()

    act(() => { container.querySelector('input')!.click() })

    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('still toggles when the selection is somewhere else on the page', () => {
    const onChange = vi.fn()
    act(() => root.render(
      <div>
        <p id="elsewhere">Unrelated text</p>
        <Switch checked={false} onChange={onChange} label="Use API models" />
      </div>,
    ))
    const range = document.createRange()
    range.selectNodeContents(container.querySelector('#elsewhere')!)
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)

    act(() => { container.querySelector('label')!.click() })

    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('marks a disabled switch so its label does not show a pointer cursor', () => {
    act(() => root.render(<Switch checked={false} onChange={vi.fn()} label="Use API models" disabled />))

    expect(container.querySelector('label')!.classList.contains('basil-switch--disabled')).toBe(true)
  })

  it('does not mark an enabled switch as disabled', () => {
    act(() => root.render(<Switch checked={false} onChange={vi.fn()} label="Use API models" />))

    expect(container.querySelector('label')!.classList.contains('basil-switch--disabled')).toBe(false)
  })
})
