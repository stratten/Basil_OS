// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SavedSetupSession } from '@/app/resume/savedSession'

import { ResumeChoice } from './ResumeChoice'

let container: HTMLElement
let root: Root

const SESSION: SavedSetupSession = {
  stage: 'conversation',
  summary: '',
  modelAccess: { mode: 'provider_key', resolved: true },
  interactionStyle: [],
  agenda: [
    { id: 'a', title: 'One', intent: '', kind: 'action', source: 'catalog', status: 'completed' },
    { id: 'b', title: 'Two', intent: '', kind: 'action', source: 'catalog', status: 'pending' },
    { id: 'c', title: 'Three', intent: '', kind: 'action', source: 'catalog', status: 'pending' },
  ],
  ageDays: 1,
  advisoryAfterDays: 3,
}

function render(session: SavedSetupSession, onResume = vi.fn(), onStartOver = vi.fn()) {
  act(() => { root.render(<ResumeChoice session={session} onResume={onResume} onStartOver={onStartOver} />) })
  return { onResume, onStartOver }
}

function button(label: string): HTMLButtonElement {
  return [...container.querySelectorAll('button')].find(candidate => candidate.textContent === label) as HTMLButtonElement
}

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

describe('ResumeChoice', () => {
  it('says when setup was started and how far it got, without an advisory for a recent session', () => {
    render(SESSION)

    expect(container.textContent).toContain('You started setting up Basil yesterday, and we had finished 1 of 3 things on the list.')
    expect(container.querySelector('.resume-choice-advisory')).toBeNull()
    expect(button('Pick up where we left off').className).toBe('primary-button')
    expect(button('Start from the top').className).toBe('secondary-button')
  })

  it('advises starting from the top for an old session while keeping both choices', () => {
    render({ ...SESSION, ageDays: 9 })

    expect(container.querySelector('.resume-choice-advisory')?.textContent).toContain("I'd suggest starting from the top, but you can pick up where you left off if you prefer.")
    expect(container.textContent).toContain('9 days ago')
    expect(button('Start from the top').className).toBe('primary-button')
    expect(button('Pick up where we left off').className).toBe('secondary-button')
  })

  it('leaves out the count when there is no agenda', () => {
    render({ ...SESSION, agenda: [] })

    expect(container.textContent).toContain('You started setting up Basil yesterday.')
    expect(container.textContent).not.toContain('things on the list')
  })

  it('reports which choice was made', () => {
    const { onResume, onStartOver } = render(SESSION)

    act(() => { button('Pick up where we left off').click() })
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(onStartOver).not.toHaveBeenCalled()

    act(() => { button('Start from the top').click() })
    expect(onStartOver).toHaveBeenCalledTimes(1)
  })
})
