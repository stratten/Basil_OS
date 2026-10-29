import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SCOPE = 'html[data-surface-finish="metal_backdrop"]'

describe('Setup Assistant resume toast surface finish', () => {
  const entry = readFileSync('src/entries/setup-assistant-resume-toast.tsx', 'utf8')
  const finishCss = readFileSync('src/styles/resume-toast-surface-finish.css', 'utf8')

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import '../styles/resume-toast-surface-finish.css'")
    expect(entry).toContain('enableBackdropSurfaceFinish()')
  })

  it('clears only the toast body, and only under the background-only finish', () => {
    expect(finishCss).toContain(`${SCOPE} .setup-assistant-resume-toast {\n  background: transparent;\n}`)
    expect(finishCss.split(SCOPE).length - 1).toBe((finishCss.match(/\{/g) ?? []).length)
  })
})
