// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

vi.mock('./wrapUpReferenceExport', () => ({
  copyWrapUpReferenceMarkdown: vi.fn().mockResolvedValue(undefined),
  downloadWrapUpReferencePdf: vi.fn().mockResolvedValue('PDF saved.'),
}))

vi.mock('@/services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api')>()),
  fetchExpressReceipt: vi.fn().mockResolvedValue({ items: [] }),
}))

import { SetupWrapUpPanel, type SetupWrapUpPanelProps } from './SetupWrapUpPanel'

let container: HTMLElement
let root: Root

function render(props: Partial<SetupWrapUpPanelProps>) {
  act(() => {
    root.render(
      <SetupWrapUpPanel wasSkipped={false} isFinalizingWrapUp={false} finalizeError={null} {...props} />,
    )
  })
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

function expectTipsAndPointer() {
  expect(container.querySelector('.setup-wrapup-window-basics')).not.toBeNull()
  expect(container.textContent).toContain('⌘E')
  expect(container.textContent).toContain('⌘↵')
  expect(container.querySelector('.setup-wrapup-settings-pointer')).not.toBeNull()
}

describe('SetupWrapUpPanel window shortcut tips', () => {
  it('shows the tips and the settings pointer when setup was skipped', () => {
    render({ wasSkipped: true })
    expectTipsAndPointer()
  })

  it('shows the tips and the settings pointer beside the recap', () => {
    render({
      wrapUpProposal: { recap: 'We set up your model.', recommended_next_steps: [], optional_breadth: null },
    })
    expect(container.textContent).toContain('We set up your model.')
    expectTipsAndPointer()
  })

  it('shows the tips and the settings pointer when the recap failed', () => {
    render({ finalizeError: 'boom' })
    expectTipsAndPointer()
  })

  it('shows the tips and the settings pointer in the nothing-landed fallback', () => {
    render({})
    expectTipsAndPointer()
  })

  it('keeps the export buttons behind a collapsed "Save a copy" disclosure', async () => {
    const { copyWrapUpReferenceMarkdown } = await import('./wrapUpReferenceExport')
    render({
      wrapUpProposal: { recap: 'We set up your model.', recommended_next_steps: [], optional_breadth: null },
    })

    const disclosure = container.querySelector<HTMLDetailsElement>('details.setup-wrapup-save-copy')!
    expect(disclosure.querySelector('summary')!.textContent).toBe('Save a copy')
    expect(disclosure.open).toBe(false)
    const labels = [...disclosure.querySelectorAll('button')].map(button => button.textContent)
    expect(labels).toEqual(['Download PDF', 'Copy Markdown'])
    expect(container.querySelectorAll('button')).toHaveLength(2)

    disclosure.open = true
    const copyButton = [...disclosure.querySelectorAll('button')].find(button => button.textContent === 'Copy Markdown')!
    await act(async () => { copyButton.click() })
    expect(copyWrapUpReferenceMarkdown).toHaveBeenCalledTimes(1)
    expect(container.querySelector('.setup-wrapup-export-status')!.textContent).toBe('Markdown copied.')
  })

  it('does not show the save disclosure when there is no recap', () => {
    render({ wasSkipped: true })
    expect(container.querySelector('.setup-wrapup-save-copy')).toBeNull()
  })

  it('does not show the tips while the recap is still being prepared', () => {
    render({ isFinalizingWrapUp: true })
    expect(container.querySelector('.setup-wrapup-window-basics')).toBeNull()
  })
})

const PROBLEM = { message: 'The local model ran out of memory on this Mac.', detail: 'llama_decode returned -3' }

describe('SetupWrapUpPanel unresolved setup problem', () => {
  it('says setup stopped early instead of "all set", with Show logs and Report a problem but no Retry', () => {
    const onShowLogs = vi.fn()
    const onReport = vi.fn()
    render({ problem: PROBLEM, onShowLogs, onReport })

    expect(container.querySelector('h1')!.textContent).toBe("Setup didn't finish.")
    expect(container.textContent).not.toContain("I'm ready when you are.")
    expect(container.querySelector('[role="alert"]')!.textContent).toContain(PROBLEM.message)
    const labels = [...container.querySelectorAll('.setup-wrapup-problem button')].map(button => button.textContent)
    expect(labels).toEqual(['Show logs', 'Report a problem'])
    expect(container.textContent).not.toContain('Retry')
    expectTipsAndPointer()

    act(() => { container.querySelectorAll<HTMLButtonElement>('.setup-wrapup-problem button')[0].click() })
    expect(onShowLogs).toHaveBeenCalledWith('llama_decode returned -3')
  })

  it('keeps the calm fallback when there is no problem', () => {
    render({ problem: null })

    expect(container.querySelector('h1')!.textContent).toBe("I'm ready when you are.")
    expect(container.querySelector('.setup-wrapup-problem')).toBeNull()
  })

  it('does not show the problem over a recap, a skip, or a failed recap', () => {
    render({ problem: PROBLEM, wrapUpProposal: { recap: 'We set up your model.', recommended_next_steps: [], optional_breadth: null } })
    expect(container.querySelector('.setup-wrapup-problem')).toBeNull()
    expect(container.textContent).toContain('We set up your model.')

    render({ problem: PROBLEM, wasSkipped: true })
    expect(container.querySelector('.setup-wrapup-problem')).toBeNull()
    expect(container.querySelector('h1')!.textContent).toBe('I saved your spot.')

    render({ problem: PROBLEM, finalizeError: 'boom' })
    expect(container.querySelector('.setup-wrapup-problem')).toBeNull()
  })
})

describe('SetupWrapUpPanel saved choices', () => {
  const STYLE = ['Keep replies short.']
  const IMPORT = { entries_added: 2, facts_proposed: 0, fact_titles: [], note_titles: [] }

  it('lists the saved preferences in the nothing-landed fallback', () => {
    render({ savedInteractionStyle: STYLE })

    expect(container.querySelector('.setup-wrapup-saved-choices')!.textContent).toContain('Keep replies short.')
    expect(container.querySelector('h1')!.textContent).toBe("I'm ready when you are.")
  })

  it('lists the saved preferences and the import in every variant that has a footer', () => {
    const variants: Partial<SetupWrapUpPanelProps>[] = [
      { wasSkipped: true },
      { wrapUpProposal: { recap: 'We set up your model.', recommended_next_steps: [], optional_breadth: null } },
      { finalizeError: 'boom' },
      { problem: PROBLEM },
      {},
    ]
    for (const variant of variants) {
      render({ ...variant, savedInteractionStyle: STYLE, importedContext: IMPORT })
      const block = container.querySelector('.setup-wrapup-saved-choices')
      expect(block, JSON.stringify(variant)).not.toBeNull()
      expect(block!.textContent).toContain('Keep replies short.')
      expect(block!.textContent).toContain('2 notes are in your searchable history.')
    }
  })

  it('shows no saved-choices block when nothing was saved, and none while the recap is being prepared', () => {
    render({})
    expect(container.querySelector('.setup-wrapup-saved-choices')).toBeNull()

    render({ isFinalizingWrapUp: true, savedInteractionStyle: STYLE })
    expect(container.querySelector('.setup-wrapup-saved-choices')).toBeNull()
  })
})
