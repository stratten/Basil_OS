import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/styles/connections-settings.css', 'utf8')

function ruleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^{}]*)\\}`))
  if (!match) throw new Error(`No rule for ${selector}`)
  return match[1]
}

describe('connection tool policy colors', () => {
  it('maps always allow to green, always ask to yellow, and never allow to red from the theme tokens', () => {
    expect(ruleBody('.connections-tool-row[data-policy="always_allow"]')).toContain('--tool-policy-base: var(--success-base)')
    expect(ruleBody('.connections-tool-row[data-policy="always_ask"]')).toContain('--tool-policy-base: var(--warning-base')
    expect(ruleBody('.connections-tool-row[data-policy="never_allow"]')).toContain('--tool-policy-base: var(--error-base')
  })

  it('colors only the policy control, with no colored edge on the row, keeping the text legible', () => {
    expect(css).not.toMatch(/\.connections-tool-row\[data-policy\]\s*\{/)
    expect(css).not.toContain('border-left: 3px solid var(--tool-policy-base)')
    const control = ruleBody('.connections-tool-row[data-policy] .connections-tool-row-policy')
    expect(control).toContain('var(--tool-policy-base)')
    expect(control).toMatch(/color: color-mix\(in srgb, var\(--tool-policy-base\) 55%, var\(--text-primary\)\)/)
  })
})
