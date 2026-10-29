// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import TokenizedSelect from '@shared/TokenizedSelect'

let container: HTMLElement
let root: Root
let style: HTMLStyleElement

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  style = document.createElement('style')
  style.textContent = '.compact-trigger { font-size: 13px; }'
  document.head.appendChild(style)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  style.remove()
})

describe('TokenizedSelect menu', () => {
  it('opens with the same font size as its trigger even though it renders into document.body', () => {
    act(() => {
      root.render(
        <TokenizedSelect
          value="a"
          className="compact-trigger"
          ariaLabel="Model"
          options={[{ value: 'a', label: 'Model A' }, { value: 'b', label: 'Model B' }]}
          onValueChange={() => undefined}
        />,
      )
    })
    act(() => { container.querySelector<HTMLButtonElement>('.tokenized-select__trigger')!.click() })
    const menu = document.body.querySelector<HTMLElement>('.tokenized-select__menu')
    expect(menu).not.toBeNull()
    expect(container.contains(menu)).toBe(false)
    expect(menu!.style.fontSize).toBe('13px')
  })
})
