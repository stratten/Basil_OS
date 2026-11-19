// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import CollapsibleRegion from './CollapsibleRegion'

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

function renderRegion(expanded: boolean) {
  act(() => {
    root.render(
      <CollapsibleRegion expanded={expanded}>
        <input aria-label="Draft" defaultValue="keep me" />
      </CollapsibleRegion>,
    )
  })
  return container.firstElementChild as HTMLElement
}

describe('CollapsibleRegion', () => {
  it('starts collapsed: content stays mounted but inert and hidden from assistive technology', () => {
    const frame = renderRegion(false)
    expect(frame.classList.contains('is-collapsed')).toBe(true)
    expect(frame.hasAttribute('inert')).toBe(true)
    expect(frame.getAttribute('aria-hidden')).toBe('true')
    expect(frame.querySelector('input')!.value).toBe('keep me')
  })

  it('opens and closes without unmounting the content', async () => {
    const frame = renderRegion(false)
    const input = frame.querySelector('input')!
    input.value = 'edited while closed'

    await act(async () => {
      renderRegion(true)
    })
    expect(frame.classList.contains('is-collapsed')).toBe(false)
    expect(frame.hasAttribute('inert')).toBe(false)

    await act(async () => {
      renderRegion(false)
    })
    expect(frame.hasAttribute('inert')).toBe(true)
    expect(container.querySelector('input')).toBe(input)
    expect(input.value).toBe('edited while closed')
  })
})
