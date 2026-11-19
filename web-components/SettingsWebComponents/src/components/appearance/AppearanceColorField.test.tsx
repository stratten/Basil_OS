// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AppearanceColorField } from './AppearanceColorField'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('AppearanceColorField', () => {
  it('renders one compact trigger and reports its RGB picker request', () => {
    const onRequestPicker = vi.fn()
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root: Root = createRoot(container)

    act(() => {
      root.render(
        <AppearanceColorField
          id="test-color"
          label="Primary Color:"
          fieldId="primary"
          red={0}
          green={0.188}
          blue={0.529}
          onRequestPicker={onRequestPicker}
        />,
      )
    })

    const trigger = container.querySelector<HTMLButtonElement>('#test-color')!
    expect(container.querySelector('input[type="color"]')).toBeNull()
    expect(container.querySelector('.appearance-color-field-swatch')).toBeNull()
    expect(trigger.getAttribute('aria-label')).toBe('Primary Color: #003087')
    expect(trigger.style.backgroundColor).toBe('rgb(0, 48, 135)')

    act(() => {
      trigger.click()
    })

    expect(onRequestPicker).toHaveBeenCalledWith({ fieldId: 'primary', red: 0, green: 0.188, blue: 0.529 })

    act(() => {
      root.unmount()
    })
    container.remove()
  })
})
