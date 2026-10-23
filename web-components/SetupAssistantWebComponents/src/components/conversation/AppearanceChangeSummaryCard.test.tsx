// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, expect, it } from 'vitest'

import type { SetupAppearanceChangeSummary } from '@/types'

import { AppearanceChangeSummaryCard } from './AppearanceChangeSummaryCard'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function renderCard(summary: SetupAppearanceChangeSummary) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root: Root = createRoot(container)
  act(() => {
    root.render(<AppearanceChangeSummaryCard summary={summary} />)
  })
  return { container, root }
}

describe('AppearanceChangeSummaryCard', () => {
  it('renders old and new color swatches using the supplied CSS colors', () => {
    const { container, root } = renderCard({
      rows: [{ kind: 'color', label: 'Background', oldColor: 'rgb(255, 255, 255)', newColor: 'rgb(26, 26, 26)' }],
      contrastWarning: null,
    })

    const row = container.querySelector('.appearance-change-row')!
    const swatches = row.querySelectorAll<HTMLElement>('.appearance-change-swatch')
    expect(row.querySelector('.appearance-change-label')?.textContent).toBe('Background')
    expect(swatches).toHaveLength(2)
    expect(swatches[0].style.backgroundColor).toBe('rgb(255, 255, 255)')
    expect(swatches[1].style.backgroundColor).toBe('rgb(26, 26, 26)')

    act(() => root.unmount())
    container.remove()
  })

  it('renders font names instead of swatches for a font change', () => {
    const { container, root } = renderCard({
      rows: [{ kind: 'font', label: 'Font', oldFont: 'Arial', newFont: 'Menlo' }],
      contrastWarning: null,
    })

    expect(container.querySelectorAll('.appearance-change-swatch')).toHaveLength(0)
    expect([...container.querySelectorAll('.appearance-change-font-name')].map(node => node.textContent))
      .toEqual(['Arial', 'Menlo'])

    act(() => root.unmount())
    container.remove()
  })

  it('renders a contrast warning only when the backend supplied one', () => {
    const withWarning = renderCard({
      rows: [{ kind: 'color', label: 'Text', oldColor: 'rgb(0, 0, 0)', newColor: 'rgb(20, 20, 20)' }],
      contrastWarning: { ratio: 1.8, requiredRatio: 4.5 },
    })
    expect(withWarning.container.querySelector('.appearance-change-contrast-warning')?.textContent)
      .toContain('1.8:1')
    act(() => withWarning.root.unmount())
    withWarning.container.remove()

    const withoutWarning = renderCard({
      rows: [{ kind: 'color', label: 'Text', oldColor: 'rgb(0, 0, 0)', newColor: 'rgb(20, 20, 20)' }],
      contrastWarning: null,
    })
    expect(withoutWarning.container.querySelector('.appearance-change-contrast-warning')).toBeNull()
    act(() => withoutWarning.root.unmount())
    withoutWarning.container.remove()
  })
})
