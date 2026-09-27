// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { StringListEditor, cleanedStringList, optionalTrimmed } from './StringListEditor'

let container: HTMLElement
let root: Root

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function setNativeInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function render(values: string[], onChange: (values: string[]) => void, maxCount = 8) {
  act(() => {
    root.render(<StringListEditor label="Hints" values={values} placeholder="Hint" maxCount={maxCount} onChange={onChange} />)
  })
}

describe('StringListEditor', () => {
  it('shows an empty-state message when there are no values', () => {
    render([], () => {})
    expect(container.querySelector('.string-list-editor-empty')?.textContent).toBe('None configured.')
  })

  it('renders one input per value', () => {
    render(['a', 'b'], () => {})
    expect(container.querySelectorAll('.string-list-editor-input').length).toBe(2)
  })

  it('appends an empty entry when Add is clicked', () => {
    let latest: string[] = ['a']
    render(latest, (next) => { latest = next })
    act(() => { container.querySelector<HTMLButtonElement>('.string-list-editor-add')!.click() })
    expect(latest).toEqual(['a', ''])
  })

  it('disables Add once maxCount is reached', () => {
    render(['a', 'b'], () => {}, 2)
    expect(container.querySelector<HTMLButtonElement>('.string-list-editor-add')!.disabled).toBe(true)
  })

  it('removes the entry at the clicked index', () => {
    let latest: string[] = ['a', 'b', 'c']
    render(latest, (next) => { latest = next })
    act(() => { container.querySelectorAll<HTMLButtonElement>('.string-list-editor-remove')[1].click() })
    expect(latest).toEqual(['a', 'c'])
  })

  it('edits the value at the given index in place', () => {
    let latest: string[] = ['a', 'b']
    render(latest, (next) => { latest = next })
    const input = container.querySelectorAll<HTMLInputElement>('.string-list-editor-input')[1]
    act(() => { setNativeInputValue(input, 'changed') })
    expect(latest).toEqual(['a', 'changed'])
  })
})

describe('cleanedStringList', () => {
  it('trims and drops empty entries', () => {
    expect(cleanedStringList([' a ', '', '  ', 'b'])).toEqual(['a', 'b'])
  })

  it('returns an empty array when every entry is blank', () => {
    expect(cleanedStringList(['', '   '])).toEqual([])
  })
})

describe('optionalTrimmed', () => {
  it('returns undefined for blank input', () => {
    expect(optionalTrimmed('   ')).toBeUndefined()
  })

  it('returns the trimmed value otherwise', () => {
    expect(optionalTrimmed('  hi  ')).toBe('hi')
  })
})
