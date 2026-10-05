// @vitest-environment jsdom
import { act, type ReactElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, expect, it } from 'vitest'

import { SetupWrapUpPanel } from '@/components/wrapup/SetupWrapUpPanel'

import { AgendaConfirmationCard } from './AgendaConfirmationCard'
import { InlineDillDraftCard } from './InlineDillDraftCard'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function renderElement(element: ReactElement) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root: Root = createRoot(container)
  act(() => {
    root.render(element)
  })
  return {
    container,
    cleanup: () => {
      act(() => root.unmount())
      container.remove()
    },
  }
}

describe('setup assistant markdown surfaces', () => {
  it('renders markdown in the wrap-up recap and optional breadth and flattens next-step chips', () => {
    const { container, cleanup } = renderElement(
      <SetupWrapUpPanel
        wasSkipped={false}
        isFinalizingWrapUp={false}
        finalizeError={null}
        wrapUpProposal={{
          recap: 'We set up **Dill**.\n\n- Hotkey ready\n- Voice deferred',
          recommended_next_steps: [{ id: 'step-1', label: 'Try **Dill**', message: 'Press `⌥D` in Mail' }],
          optional_breadth: 'Later: **writing samples**',
        }}
      />,
    )

    const recap = container.querySelector('.setup-wrapup-recap')!
    expect(recap.querySelector('strong')?.textContent).toBe('Dill')
    expect([...recap.querySelectorAll('li')].map(item => item.textContent)).toEqual(['Hotkey ready', 'Voice deferred'])
    expect(container.querySelector('.setup-wrapup-breadth strong')?.textContent).toBe('writing samples')
    const step = container.querySelector('.setup-wrapup-next-steps li')!
    expect(step.querySelector('strong')?.textContent).toBe('Try Dill')
    expect(step.querySelector('span')?.textContent).toBe('Press ⌥D in Mail')
    expect(container.textContent).not.toContain('**')

    cleanup()
  })

  it('renders markdown in the agenda confirmation prompt', () => {
    const { container, cleanup } = renderElement(
      <AgendaConfirmationCard
        confirmation={{ id: 'c1', agendaItemId: 'a1', prompt: 'Did the **Dill** draft land?', createdAt: '2026-10-05T12:00:00Z' }}
        onResolve={() => {}}
      />,
    )

    expect(container.querySelector('.agenda-confirmation-prompt strong')?.textContent).toBe('Dill')
    expect(container.textContent).not.toContain('**')

    cleanup()
  })

  it('renders markdown in the Dill draft body', () => {
    const { container, cleanup } = renderElement(
      <InlineDillDraftCard
        draft={{
          assistantSessionId: 's1',
          status: 'completed',
          resultText: 'Hi Sam,\n\n**Thursday** works.\n\n- Bring slides\n- Book room',
          createdAt: '2026-10-05T12:00:00Z',
        }}
      />,
    )

    const body = container.querySelector('.inline-dill-draft-body')!
    expect(body.querySelector('strong')?.textContent).toBe('Thursday')
    expect(body.querySelectorAll('li')).toHaveLength(2)
    expect(body.textContent).not.toContain('**')

    cleanup()
  })
})
