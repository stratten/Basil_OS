import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// The local server styles use theme tokens only, and no card carries a thick accent edge.
const css = readFileSync('src/styles/local-servers.css', 'utf8')

describe('local server styles', () => {
  it('uses no literal white or black', () => {
    expect(css).not.toMatch(/#fff(?:fff)?\b|#000(?:000)?\b/i)
    expect(css).not.toMatch(/rgba?\(\s*(?:255\s*,\s*255\s*,\s*255|0\s*,\s*0\s*,\s*0)/)
  })

  it('has no thick colored edge on any side', () => {
    expect(css).not.toMatch(/border-(?:left|right|top|bottom):\s*[3-9]px/)
  })

  it('colors status text only from the theme tokens', () => {
    expect(css).toMatch(/\.connections-local-status-ok\s*\{[^}]*var\(--success-base\)/)
    expect(css).toMatch(/\.connections-local-status-error\s*\{[^}]*var\(--error-text\)/)
  })

  it('is imported by the Connections app so the rules are bundled', () => {
    const app = readFileSync('src/app/ConnectionsSettingsApp.tsx', 'utf8')
    expect(app).toContain("import '../styles/local-servers.css'")
  })
})
