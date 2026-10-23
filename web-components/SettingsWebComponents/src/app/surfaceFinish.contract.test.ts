import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SCOPE = 'html[data-surface-finish="metal_backdrop"]'

describe('Settings window surface finish', () => {
  const entry = readFileSync('src/main.tsx', 'utf8')
  const finishCss = readFileSync('src/styles/settings-surface-finish.css', 'utf8')

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import './styles/settings-surface-finish.css'")
    expect(entry).toContain('enableBackdropSurfaceFinish()')
  })

  it('clears the window chrome, navigation, and main column only', () => {
    expect(finishCss).toContain(`${SCOPE} :is(`)
    for (const chrome of ['.basil-window-header', '.basil-window-content', '.settings-shell-navigation', '.settings-shell-content']) {
      expect(finishCss).toContain(chrome)
    }
    expect(finishCss.split(SCOPE).length - 1).toBe(1)
    expect(finishCss).not.toContain('-section')
  })
})
