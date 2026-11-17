import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// The agenda cards that recede (finished, skipped, deferred) dim the whole card, text included. The text is the system label color, about 85% black, so the effective gray is 0.85 times the opacity. Black at that strength on a white card needs an opacity of at least 0.72 to stay above 6:1.
const css = readFileSync(resolve(__dirname, 'setup-assistant.agenda.css'), 'utf8')
const MINIMUM_OPACITY = 0.72

function opacityOf(selector: string): number {
  const block = css.match(new RegExp(`${selector.replace(/[.]/g, '\\.')}\\s*\\{([^}]*)\\}`))
  expect(block, `rule for ${selector}`).not.toBeNull()
  const value = block![1].match(/opacity:\s*([0-9.]+)/)
  expect(value, `opacity in ${selector}`).not.toBeNull()
  return Number(value![1])
}

function contrastOnWhite(opacityOfBlack: number): number {
  const channel = Math.round(255 * (1 - opacityOfBlack))
  const linear = (v: number) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  const luminance = linear(channel)
  return 1.05 / (luminance + 0.05)
}

describe('agenda card dimming', () => {
  it.each([
    '.setup-agenda-sidebar-item.state-completed',
    '.setup-agenda-sidebar-item.state-deferred',
  ])('%s keeps its text readable', (selector) => {
    const opacity = opacityOf(selector)
    expect(opacity).toBeGreaterThanOrEqual(MINIMUM_OPACITY)
    expect(contrastOnWhite(0.85 * opacity)).toBeGreaterThanOrEqual(4.5 + 1.5)
  })

  it('dims skipped cards the same as deferred ones', () => {
    expect(css).toMatch(/\.setup-agenda-sidebar-item\.state-skipped,\s*\.setup-agenda-sidebar-item\.state-deferred\s*\{/)
  })
})
