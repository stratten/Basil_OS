import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// The Connections header and its status line are plain: nothing floats, nothing sits on a slab of its own color, and no card carries a thick accent edge. These rules guard against that styling coming back.
const css = readFileSync('src/styles/connections-settings.css', 'utf8')
const reasoningCss = readFileSync('src/styles/reasoning-api-models.css', 'utf8')
const transcriptionCss = readFileSync('src/styles/transcription-api-models.css', 'utf8')

function rule(source: string, selector: string): string {
  const escaped = selector.replace(/[.[\]'=()>*]/g, '\\$&')
  const match = source.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))
  expect(match, `rule for ${selector}`).not.toBeNull()
  return match![1]
}

describe('Connections header and status line', () => {
  it('does not float or paint its own background', () => {
    const header = rule(css, '.connections-panel-header')
    expect(header).not.toMatch(/position:\s*sticky|position:\s*fixed/)
    expect(header).not.toMatch(/background/)
  })

  it('shows the connection summary as plain text with no card, fill or accent edge', () => {
    const summary = rule(css, '.connections-summary')
    expect(summary).not.toMatch(/background|border|box-shadow|padding/)
  })

  it('keeps the add button at the same look as the other add buttons, only protected from shrinking', () => {
    expect(css).not.toContain('connections-add-primary')
    const guard = rule(css, '.connections-panel-header-actions .connections-add-toggle')
    expect(guard).toMatch(/flex-shrink:\s*0/)
    expect(guard).toMatch(/white-space:\s*nowrap/)
    expect(guard).not.toMatch(/box-shadow|font-weight|min-height|padding/)
  })
})

describe('API models notes', () => {
  it.each([
    ['reasoning', reasoningCss, '.reasoning-api-models-master-note'],
    ['transcription', transcriptionCss, '.transcription-api-models-master-note'],
  ])('the %s master-switch note is plain text without an accent edge', (_name, source, selector) => {
    expect(rule(source, selector)).not.toMatch(/border|background|box-shadow/)
  })
})
