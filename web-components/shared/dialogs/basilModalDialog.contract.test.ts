// @vitest-environment node

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

describe('shared modal stylesheet', () => {
  const css = readFileSync(fileURLToPath(new URL('./basil-modal-dialog.css', import.meta.url)), 'utf8')
  const rule = (selector: string) => css.slice(css.indexOf(`${selector} {`), css.indexOf('}', css.indexOf(`${selector} {`)))

  it('draws the card with the thin separator border, large radius, and dark shadow the agent task dialog uses', () => {
    const card = rule('.basil-modal-dialog')
    expect(card).toContain('border: var(--border-thin) solid var(--separator-color)')
    expect(card).toContain('border-radius: var(--corner-radius-large)')
    expect(card).toContain('box-shadow: var(--shadow-dark)')
  })

  it('keeps the backdrop inside its positioned ancestor and leaves the title bar clear in a window', () => {
    expect(rule('.basil-modal-backdrop')).toContain('position: absolute')
    expect(rule('.basil-modal-backdrop')).not.toContain('fixed')
    expect(rule('.basil-webkit-window-surface > .basil-modal-backdrop')).toContain('top: 44px')
  })

  it('fixes the backdrop to the viewport only through the modifier, and widens the card through its own modifier', () => {
    expect(rule('.basil-modal-backdrop--viewport')).toContain('position: fixed')
    expect(rule('.basil-modal-dialog--wide')).toContain('width: min(720px, 100%)')
  })
})
