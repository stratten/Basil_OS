// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AppearancePresetSwatches } from './AppearancePresetSwatches'
import { APPEARANCE_PRESETS } from '../data/appearancePresets'

let container: HTMLElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  container.remove()
})

describe('AppearancePresetSwatches', () => {
  it('renders one button per preset with an accessible name', () => {
    act(() => {
      root.render(<AppearancePresetSwatches onSelect={() => {}} />)
    })
    const buttons = container.querySelectorAll('.appearance-preset-swatch')
    expect(buttons.length).toBe(APPEARANCE_PRESETS.length)
    expect(container.querySelector('[aria-label="Precursor"]')).not.toBeNull()
  })

  it('invokes onSelect with the matching preset when a swatch is clicked', () => {
    const onSelect = vi.fn()
    act(() => {
      root.render(<AppearancePresetSwatches onSelect={onSelect} />)
    })
    const midnightButton = container.querySelector<HTMLButtonElement>('[aria-label="Midnight"]')!
    act(() => {
      midnightButton.click()
    })
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'midnight', name: 'Midnight' }))
  })
})
