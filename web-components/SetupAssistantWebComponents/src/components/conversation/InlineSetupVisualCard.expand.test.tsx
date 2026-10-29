// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupInlineVisual } from '@/types'

import { InlineSetupVisualCard } from './InlineSetupVisualCard'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

const screenshot: SetupInlineVisual = {
  id: 'activity-capture',
  kind: 'screenshot',
  webPath: '/images/setup/activity_capture.png',
  alt: 'Activity capture summary',
  caption: 'This is what a day of captured activity looks like.',
} as SetupInlineVisual

const composite: SetupInlineVisual = {
  ...screenshot,
  id: 'compare',
  kind: 'composite',
  secondaryWebPath: '/images/setup/compare_b.png',
  secondaryAlt: 'Second view',
} as SetupInlineVisual

const icon: SetupInlineVisual = {
  ...screenshot,
  id: 'status-icon',
  kind: 'icon',
} as SetupInlineVisual

function renderCard(visual: SetupInlineVisual) {
  act(() => { root.render(<InlineSetupVisualCard visual={visual} />) })
}

const click = (element: Element) => act(() => { element.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
const lightbox = () => document.body.querySelector('[data-testid="setup-image-lightbox"]')

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('InlineSetupVisualCard image expansion', () => {
  it('opens the full-size image from a screenshot and closes it with the close button', () => {
    renderCard(screenshot)
    expect(lightbox()).toBeNull()

    click(container.querySelector('button.inline-setup-visual-zoom') as HTMLElement)

    const dialog = document.body.querySelector('[role="dialog"]')
    expect(dialog?.getAttribute('aria-label')).toBe('Activity capture summary')
    expect(dialog?.querySelector('img')?.getAttribute('src')).toBe('/images/setup/activity_capture.png')
    expect(dialog?.textContent).toContain('This is what a day of captured activity looks like.')

    click(document.body.querySelector('button[aria-label="Close image"]') as HTMLElement)
    expect(lightbox()).toBeNull()
  })

  it('closes on Escape and when the backdrop is pressed, but not when the image is pressed', () => {
    renderCard(screenshot)
    click(container.querySelector('button.inline-setup-visual-zoom') as HTMLElement)

    act(() => { document.body.querySelector('.setup-image-lightbox-image')?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    expect(lightbox()).not.toBeNull()

    act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(lightbox()).toBeNull()

    click(container.querySelector('button.inline-setup-visual-zoom') as HTMLElement)
    act(() => { lightbox()?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    expect(lightbox()).toBeNull()
  })

  it('lets each image of a composite open on its own', () => {
    renderCard(composite)
    const zooms = container.querySelectorAll<HTMLElement>('button.inline-setup-visual-zoom')
    expect(zooms).toHaveLength(2)

    click(zooms[1])

    expect(document.body.querySelector('.setup-image-lightbox-image')?.getAttribute('src')).toBe('/images/setup/compare_b.png')
    expect(document.body.querySelector('[role="dialog"]')?.getAttribute('aria-label')).toBe('Second view')
  })

  it('leaves small inline status icons as plain images', () => {
    renderCard(icon)

    expect(container.querySelector('button.inline-setup-visual-zoom')).toBeNull()
    expect(container.querySelector('img.inline-setup-visual-icon')).not.toBeNull()
  })
})
