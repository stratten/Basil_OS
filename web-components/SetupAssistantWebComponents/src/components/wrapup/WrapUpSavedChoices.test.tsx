// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupImportedContextSummary } from '@/state/setupAssistantStore'

import { WrapUpSavedChoices, type WrapUpSavedChoicesProps } from './WrapUpSavedChoices'

const IMPORT_WITH_PROFILE: SetupImportedContextSummary = {
  entries_added: 4,
  facts_proposed: 1,
  fact_titles: ['Works as a nurse'],
  note_titles: [],
  profile_updated: true,
  profile_summary: 'You are a nurse in Leeds.',
}

let container: HTMLElement
let root: Root

function render(props: WrapUpSavedChoicesProps) {
  act(() => { root.render(<WrapUpSavedChoices {...props} />) })
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

describe('WrapUpSavedChoices', () => {
  it('renders nothing when no preferences were saved and nothing was imported', () => {
    render({})
    expect(container.innerHTML).toBe('')

    render({ interactionStyle: [], importedContext: { entries_added: 0, facts_proposed: 0, fact_titles: [], note_titles: [] } })
    expect(container.innerHTML).toBe('')
  })

  it('lists each saved reply preference and says they are saved to the profile', () => {
    render({ interactionStyle: ['Keep replies short.', 'Use a table when comparing options.'] })

    expect(container.querySelector('h2')!.textContent).toBe('Saved during setup')
    expect(container.textContent).toContain('saved to your profile')
    expect([...container.querySelectorAll('li')].map(item => item.textContent)).toEqual([
      'Keep replies short.',
      'Use a table when comparing options.',
    ])
  })

  it('shows two identical preference lines without a duplicate key problem', () => {
    render({ interactionStyle: ['Keep replies short.', 'Keep replies short.'] })

    expect(container.querySelectorAll('li')).toHaveLength(2)
  })

  it('shows what the import added', () => {
    render({ importedContext: IMPORT_WITH_PROFILE })

    expect(container.textContent).toContain('Your profile is already in place.')
    expect(container.textContent).toContain('You are a nurse in Leeds.')
    expect(container.textContent).toContain('4 notes are in your searchable history.')
    expect(container.textContent).toContain('1 fact is waiting for your approval.')
    expect(container.querySelectorAll('li')).toHaveLength(0)
  })

  it('shows both when both exist', () => {
    render({ interactionStyle: ['Keep replies short.'], importedContext: IMPORT_WITH_PROFILE })

    expect(container.querySelectorAll('li')).toHaveLength(1)
    expect(container.querySelector('.setup-wrapup-saved-choices__imported')).not.toBeNull()
  })
})
