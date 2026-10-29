// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

vi.mock('./wrapUpReferenceExport', () => ({
  copyWrapUpReferenceMarkdown: vi.fn().mockResolvedValue(undefined),
  downloadWrapUpReferencePdf: vi.fn().mockResolvedValue('PDF saved.'),
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
