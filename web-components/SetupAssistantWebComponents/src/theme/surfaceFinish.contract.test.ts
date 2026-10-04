import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SCOPE = 'html[data-surface-finish="metal_backdrop"]'

describe.each([
  { name: 'Setup Assistant', entry: 'src/entries/setup-assistant.tsx' },
  { name: 'Setup permissions', entry: 'src/entries/setup-permissions.tsx' },
])('$name window surface finish', ({ entry }) => {
  it('opts the window into the background-only metallic finish', () => {
    const source = readFileSync(entry, 'utf8')
    expect(source).toContain("import '@/styles/setup-assistant-surface-finish.css'")
    expect(source).toContain('enableBackdropSurfaceFinish()')
  })
})

describe('Setup Assistant finish stylesheet', () => {
  it('clears only the window header and content wrapper', () => {
    const finishCss = readFileSync('src/styles/setup-assistant-surface-finish.css', 'utf8')
    expect(finishCss).toContain(`${SCOPE} :is(`)
    expect(finishCss).toContain('.basil-window-header')
    expect(finishCss).toContain('.basil-window-content')
    expect(finishCss.split(SCOPE).length - 1).toBe(1)
    for (const solidSurface of ['.setup-card', '.permission-row']) {
      expect(finishCss).not.toContain(solidSurface)
    }
  })
})
