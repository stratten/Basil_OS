// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AppearancePreviewCard } from './AppearancePreviewCard'
import { APPEARANCE_FIXTURE_SETTINGS } from '../fixtures/appearanceFixture'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('AppearancePreviewCard', () => {
  it('derives every preview surface from the draft colors and font, with no independent state', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root: Root = createRoot(container)

    act(() => {
      root.render(<AppearancePreviewCard draft={APPEARANCE_FIXTURE_SETTINGS} />)
    })

    const card = container.querySelector<HTMLDivElement>('.appearance-preview-card')!
    expect(card.style.background).toBe('rgb(255, 255, 255)')
    expect(card.style.fontFamily).toBe('Helvetica-Light')

    const headline = container.querySelector<HTMLHeadingElement>('.appearance-preview-headline')!
    expect(headline.style.color).toBe('rgb(0, 48, 135)')

    const primaryButton = container.querySelector<HTMLButtonElement>('.appearance-preview-button-primary')!
    expect(primaryButton.style.background).toBe('rgb(0, 48, 135)')
    expect(primaryButton.disabled).toBe(true)

    act(() => {
      root.render(<AppearancePreviewCard draft={{ ...APPEARANCE_FIXTURE_SETTINGS, preferredFont: 'Menlo', primaryColorRed: 1, primaryColorGreen: 0, primaryColorBlue: 0 }} />)
    })
    expect(card.style.fontFamily).toBe('Menlo')
    expect(headline.style.color).toBe('rgb(255, 0, 0)')

    act(() => {
      root.unmount()
    })
    container.remove()
  })
})
