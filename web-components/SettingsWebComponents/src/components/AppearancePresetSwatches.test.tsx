// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AppearancePresetSwatches } from './AppearancePresetSwatches'
import { APPEARANCE_PRESETS } from '../data/appearancePresets'
import type { CustomAppearanceTheme } from '../types'

const harbor: CustomAppearanceTheme = {
  id: 'custom-0123456789abcdef0123456789abcdef',
  name: 'Harbor',
  backgroundColorRed: 0.1,
  backgroundColorGreen: 0.2,
  backgroundColorBlue: 0.3,
  primaryColorRed: 0.4,
  primaryColorGreen: 0.5,
  primaryColorBlue: 0.6,
  secondaryColorRed: 0.7,
  secondaryColorGreen: 0.8,
  secondaryColorBlue: 0.9,
  textColorRed: 1,
  textColorGreen: 0.95,
  textColorBlue: 0.9,
  surfaceFinish: 'metal',
}

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

  it('renders custom themes after the presets with a delete control only on custom themes', () => {
    const onSelectCustom = vi.fn()
    const onRequestDeleteCustom = vi.fn()
    act(() => {
      root.render(
        <AppearancePresetSwatches
          onSelect={() => {}}
          customThemes={[harbor]}
          onSelectCustom={onSelectCustom}
          onRequestDeleteCustom={onRequestDeleteCustom}
        />,
      )
    })
    const swatches = container.querySelectorAll<HTMLButtonElement>('.appearance-preset-swatch')
    expect(swatches.length).toBe(APPEARANCE_PRESETS.length + 1)
    expect(swatches[swatches.length - 1].getAttribute('aria-label')).toBe('Harbor')
    expect(container.querySelectorAll('.appearance-preset-swatch-delete').length).toBe(1)
    expect(container.querySelector('[aria-label="Delete theme Precursor"]')).toBeNull()

    act(() => {
      swatches[swatches.length - 1].click()
    })
    expect(onSelectCustom).toHaveBeenCalledWith(harbor)

    act(() => {
      container.querySelector<HTMLButtonElement>('[aria-label="Delete theme Harbor"]')!.click()
    })
    expect(onRequestDeleteCustom).toHaveBeenCalledWith(harbor)
  })

  it('disables custom delete controls while a theme request is pending', () => {
    act(() => {
      root.render(
        <AppearancePresetSwatches onSelect={() => {}} customThemes={[harbor]} onRequestDeleteCustom={() => {}} deleteDisabled />,
      )
    })
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Delete theme Harbor"]')!.disabled).toBe(true)
  })
})
