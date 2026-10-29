// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { SetupConversationMarkdown } from './SetupConversationMarkdown'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

function render(content: string, animateWords?: boolean) {
  act(() => { root.render(<SetupConversationMarkdown content={content} animateWords={animateWords} />) })
}

const words = () => Array.from(container.querySelectorAll('.setup-reveal-word'))

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('SetupConversationMarkdown word reveal', () => {
  it('renders plain text with no word spans by default', () => {
    render('I turned on read-only auto-approval.')

    expect(words()).toHaveLength(0)
    expect(container.textContent).toBe('I turned on read-only auto-approval.')
  })

  it('wraps each word in a fading span without changing the visible text', () => {
    render('I turned on **auto-approval** for you.', true)

    expect(container.textContent).toBe('I turned on auto-approval for you.')
    expect(words().map(word => word.textContent)).toEqual(['I', 'turned', 'on', 'auto-approval', 'for', 'you.'])
    expect(container.querySelector('strong .setup-reveal-word')?.textContent).toBe('auto-approval')
  })

  it('keeps earlier words mounted when more text arrives so only the new words animate in', () => {
    render('First words here', true)
    const before = words()

    render('First words here and then more', true)
    const after = words()

    expect(after.slice(0, 3)).toEqual(before)
    expect(after.slice(3).map(word => word.textContent)).toEqual(['and', 'then', 'more'])
  })

  it('animates words inside list items and across paragraphs', () => {
    render('Intro line\n\n- first item\n- second item', true)

    expect(container.querySelectorAll('li .setup-reveal-word')).toHaveLength(4)
    expect(container.querySelectorAll('p .setup-reveal-word')).toHaveLength(2)
  })
})
