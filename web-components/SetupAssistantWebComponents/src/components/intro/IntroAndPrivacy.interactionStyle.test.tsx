// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { InteractionStyleGroup } from '@/services/api'

import { IntroAndPrivacy } from './IntroAndPrivacy'
import { toggleInteractionStyleOption } from './IntroInteractionStyle'

const GROUPS: InteractionStyleGroup[] = [
  {
    id: 'length',
    title: 'How much do you want me to say?',
    multiple: false,
    options: [
      { id: 'short', label: 'Short answers, lead with the result' },
      { id: 'thorough', label: 'Walk me through the reasoning' },
    ],
  },
  {
    id: 'format',
    title: 'How should I lay it out?',
    multiple: true,
    options: [
      { id: 'bullets', label: 'Bullet points for lists' },
      { id: 'tables', label: 'Tables for comparisons' },
    ],
  },
]

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>
let savedBodies: unknown[]

function jsonResponse(body: unknown, ok = true) {
  return { ok, status: ok ? 200 : 422, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

function installFetch({ catalog = true, saveOk = true }: { catalog?: boolean; saveOk?: boolean } = {}) {
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/setup-assistant/model-access/options') {
      return Promise.resolve(jsonResponse({ options: [{ mode: 'local', available: true, requires_provider_key_input: false, local_model_id: 'phi2-2.7b' }] }))
    }
    if (path === '/setup-assistant/interaction-style') {
      if (init?.method === 'POST') {
        savedBodies.push(JSON.parse(String(init.body)))
        return Promise.resolve(saveOk
          ? jsonResponse({ saved: true, instructions: ['Lead with the answer in one or two sentences and keep replies short.'] })
          : jsonResponse({ detail: 'too long' }, false))
      }
      return catalog ? Promise.resolve(jsonResponse({ groups: GROUPS })) : Promise.reject(new Error('offline'))
    }
    return Promise.resolve(jsonResponse({ status: 'success', settings: { memory_after_task_enabled: false, skill_after_task_enabled: false } }))
  })
}

async function renderIntro(onContinue = vi.fn()) {
  await act(async () => {
    root.render(
      <IntroAndPrivacy
        selectedModelAccess={{ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true }}
        onSelectModelAccess={vi.fn()}
        onContinue={onContinue}
      />,
    )
    await Promise.resolve()
    await Promise.resolve()
  })
  return onContinue
}

const primary = () => container.querySelector<HTMLButtonElement>('.intro-step-primary')!
const option = (label: string) => Array.from(container.querySelectorAll<HTMLButtonElement>('.intro-style-option'))
  .find(button => button.textContent === label)!

async function reachNoteStep() {
  act(() => { primary().click() })
  act(() => { primary().click() })
}

beforeEach(() => {
  savedBodies = []
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

describe('toggleInteractionStyleOption', () => {
  it('swaps a single-choice group and clears it when the same statement is pressed again', () => {
    const [length] = GROUPS
    const first = toggleInteractionStyleOption({}, length, 'short')
    const swapped = toggleInteractionStyleOption(first, length, 'thorough')
    const cleared = toggleInteractionStyleOption(swapped, length, 'thorough')

    expect(first).toEqual({ length: ['short'] })
    expect(swapped).toEqual({ length: ['thorough'] })
    expect(cleared).toEqual({})
  })

  it('adds and removes statements independently in a multiple-choice group', () => {
    const format = GROUPS[1]
    const both = toggleInteractionStyleOption(toggleInteractionStyleOption({}, format, 'bullets'), format, 'tables')
    const withoutBullets = toggleInteractionStyleOption(both, format, 'bullets')

    expect(both).toEqual({ format: ['bullets', 'tables'] })
    expect(withoutBullets).toEqual({ format: ['tables'] })
  })
})

describe('IntroAndPrivacy interaction style step', () => {
  it('offers the statements on the last step with no statement selected by default', async () => {
    installFetch()
    await renderIntro()
    await reachNoteStep()

    expect(container.querySelector('h3')?.textContent).toBe('How should I work with you?')
    expect(container.querySelectorAll('.intro-style-group')).toHaveLength(2)
    expect(container.querySelectorAll('.intro-style-option[aria-pressed="true"]')).toHaveLength(0)
    expect(container.textContent).toContain('Pick one')
    expect(container.textContent).toContain('Pick any')
    expect(container.querySelector('textarea')).not.toBeNull()
  })

  it('saves the chosen statements on continue and hands their instructions to the conversation', async () => {
    installFetch()
    const onContinue = await renderIntro()
    await reachNoteStep()

    act(() => { option('Short answers, lead with the result').click() })
    act(() => { option('Bullet points for lists').click() })
    act(() => { option('Tables for comparisons').click() })
    expect(option('Short answers, lead with the result').getAttribute('aria-pressed')).toBe('true')

    await act(async () => {
      primary().click()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(savedBodies).toEqual([{ selections: { length: ['short'], format: ['bullets', 'tables'] } }])
    expect(onContinue).toHaveBeenCalledWith('', ['Lead with the answer in one or two sentences and keep replies short.'])
  })

  it('does not call the save endpoint when nothing was chosen', async () => {
    installFetch()
    const onContinue = await renderIntro()
    await reachNoteStep()

    await act(async () => {
      primary().click()
      await Promise.resolve()
    })

    expect(savedBodies).toEqual([])
    expect(onContinue).toHaveBeenCalledWith('')
  })

  it('keeps the note step working and shows the original heading when the statements cannot load', async () => {
    installFetch({ catalog: false })
    await renderIntro()
    await reachNoteStep()

    expect(container.querySelector('h3')?.textContent).toBe('Anything else I should know?')
    expect(container.querySelector('.intro-style')).toBeNull()
    expect(container.querySelector('textarea')).not.toBeNull()
  })

  it('stays on the step with an error when saving fails so the choices are not lost', async () => {
    installFetch({ saveOk: false })
    const onContinue = await renderIntro()
    await reachNoteStep()
    act(() => { option('Walk me through the reasoning').click() })

    await act(async () => {
      primary().click()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(onContinue).not.toHaveBeenCalled()
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("couldn't save")
    expect(option('Walk me through the reasoning').getAttribute('aria-pressed')).toBe('true')
  })
})
