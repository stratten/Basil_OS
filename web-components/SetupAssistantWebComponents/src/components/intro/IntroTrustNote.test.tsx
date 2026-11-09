// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { IntroTrustNote, PRIVACY_AND_DATA_FLOW_URL } from './IntroTrustNote'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<IntroTrustNote />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('IntroTrustNote', () => {
  it('says risky actions need approval and that the card explains them first', () => {
    const text = container.textContent ?? ''
    expect(text).toContain('You approve risky actions first.')
    expect(text).toContain('waits for your approval')
    expect(text).toContain('explains what the action does before you decide')
  })

  it('links to the privacy and data flow guide in a new window without leaking the opener', () => {
    const link = container.querySelector('a')!
    expect(link.getAttribute('href')).toBe(PRIVACY_AND_DATA_FLOW_URL)
    expect(PRIVACY_AND_DATA_FLOW_URL.endsWith('/docs/privacy-and-data-flow.md')).toBe(true)
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noreferrer')
  })
})
