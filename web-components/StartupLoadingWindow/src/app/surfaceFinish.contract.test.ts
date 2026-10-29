import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SCOPE = 'html[data-surface-finish="metal_backdrop"]'

describe('Startup loading window surface finish', () => {
  const entry = readFileSync('src/entries/startup-loading.tsx', 'utf8')
  const finishCss = readFileSync('src/styles/startup-loading-surface-finish.css', 'utf8')

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import '../styles/startup-loading-surface-finish.css'")
    expect(entry).toContain('enableBackdropSurfaceFinish()')
  })

  it('clears only the status body, and only under the background-only finish', () => {
    expect(finishCss).toContain(`${SCOPE} .startup-loading-body {\n  background: transparent;\n}`)
    expect(finishCss.split(SCOPE).length - 1).toBe((finishCss.match(/\{/g) ?? []).length)
  })
})
