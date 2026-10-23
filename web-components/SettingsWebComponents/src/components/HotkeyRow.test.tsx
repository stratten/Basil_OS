// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { HotkeyRow } from './HotkeyRow'
import type { HotkeyRowSnapshot } from '../types'

let container: HTMLElement
let root: Root

const ROW: HotkeyRowSnapshot = {
  id: 'agent_task',
  title: 'Paprika',
  subtitle: 'Agent',
  binding: { key: 'Space', modifiers: ['option'], enabled: true, isDoublePress: false, doublePressKey: null },
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

describe('HotkeyRow', () => {
  it('renders title, subtitle, and key caps when not editing', () => {
    act(() => {
      root.render(<HotkeyRow row={ROW} isEditing={false} isSaving={false} isDisabled={false} errorMessage={null} onEdit={vi.fn()} onCancel={vi.fn()} />)
    })
    expect(container.querySelector('.hotkey-row-title')?.textContent).toBe('Paprika')
    expect(container.querySelector('.hotkey-row-subtitle')?.textContent).toBe('Agent')
    expect(container.querySelectorAll('.hotkey-key-cap').length).toBe(2)
  })

  it('shows a Press key indicator and Cancel button while editing', () => {
    act(() => {
      root.render(<HotkeyRow row={ROW} isEditing={true} isSaving={false} isDisabled={false} errorMessage={null} onEdit={vi.fn()} onCancel={vi.fn()} />)
    })
    expect(container.querySelector('.hotkey-row-recording-indicator')?.textContent).toBe('Press key...')
    expect(container.querySelectorAll('.hotkey-key-cap').length).toBe(0)
  })

  it('calls onEdit when Edit is clicked', () => {
    const onEdit = vi.fn()
    act(() => {
      root.render(<HotkeyRow row={ROW} isEditing={false} isSaving={false} isDisabled={false} errorMessage={null} onEdit={onEdit} onCancel={vi.fn()} />)
    })
    act(() => {
      container.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onEdit).toHaveBeenCalledTimes(1)
  })

  it('calls onCancel when Cancel is clicked while editing', () => {
    const onCancel = vi.fn()
    act(() => {
      root.render(<HotkeyRow row={ROW} isEditing={true} isSaving={false} isDisabled={false} errorMessage={null} onEdit={vi.fn()} onCancel={onCancel} />)
    })
    act(() => {
      container.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('disables Edit and shows Saving while a save is in flight', () => {
    act(() => {
      root.render(<HotkeyRow row={ROW} isEditing={false} isSaving={true} isDisabled={false} errorMessage={null} onEdit={vi.fn()} onCancel={vi.fn()} />)
    })
    const button = container.querySelector<HTMLButtonElement>('button')!
    expect(button.disabled).toBe(true)
    expect(button.textContent).toBe('Saving...')
  })

  it('disables Edit until native settings initialization completes', () => {
    act(() => {
      root.render(<HotkeyRow row={ROW} isEditing={false} isSaving={false} isDisabled={true} errorMessage={null} onEdit={vi.fn()} onCancel={vi.fn()} />)
    })
    expect(container.querySelector<HTMLButtonElement>('button')?.disabled).toBe(true)
  })

  it('renders an inline error message when present', () => {
    act(() => {
      root.render(<HotkeyRow row={ROW} isEditing={false} isSaving={false} isDisabled={false} errorMessage="Failed to save hotkey." onEdit={vi.fn()} onCancel={vi.fn()} />)
    })
    expect(container.querySelector('.hotkey-row-error')?.textContent).toBe('Failed to save hotkey.')
  })
})
