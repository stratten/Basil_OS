// @vitest-environment jsdom
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useSetupAssistantTheme } from './themeBootstrap'

const stylesDirectory = join(__dirname, '../styles')
const sharedTokensFile = join(__dirname, '../../../shared/theme-layout-tokens.css')

function ThemeHost() {
  useSetupAssistantTheme()
  return null
}

function strippedCss(path: string): string {
  return readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
}

describe('Setup text size scaling (Command-plus and Command-minus)', () => {
  let container: HTMLElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    document.documentElement.style.removeProperty('--text-scale')
    window.basilSetupAssistantConfig = { theme: { textScale: 1 } }
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => { root.unmount() })
    container.remove()
    delete window.basilSetupAssistantConfig
  })

  it('applies the text size the window opens at, and every later size the app publishes', () => {
    act(() => { root.render(createElement(ThemeHost)) })
    expect(document.documentElement.style.getPropertyValue('--text-scale')).toBe('1')

    act(() => {
      window.dispatchEvent(new CustomEvent('setupAssistantThemeChanged', { detail: { theme: { textScale: 1.25 } } }))
    })
    expect(document.documentElement.style.getPropertyValue('--text-scale')).toBe('1.25')

    act(() => {
      window.dispatchEvent(new CustomEvent('setupAssistantThemeChanged', { detail: { theme: { textScale: 0.9 } } }))
    })
    expect(document.documentElement.style.getPropertyValue('--text-scale')).toBe('0.9')
  })

  it('defines every font size token the setup styles use, so no text falls back to a fixed size that ignores the scale', () => {
    const defined = new Set(
      [...strippedCss(sharedTokensFile).matchAll(/(--font-size-[a-z0-9-]+)\s*:/g)].map(match => match[1]),
    )
    expect(defined.size).toBeGreaterThan(10)

    const undefinedUses: string[] = []
    for (const file of readdirSync(stylesDirectory).filter(name => name.endsWith('.css'))) {
      for (const match of strippedCss(join(stylesDirectory, file)).matchAll(/var\(\s*(--font-size-[a-z0-9-]+)/g)) {
        if (!defined.has(match[1])) undefinedUses.push(`${file} ${match[1]}`)
      }
    }
    expect(undefinedUses).toEqual([])
  })

  it('reaches the shared font size tokens through the import chain the setup stylesheet already uses', () => {
    expect(strippedCss(join(stylesDirectory, 'setup-assistant.shared.css'))).toContain("@import '../../../AgentTaskResult/src/styles/theme.css';")
    expect(strippedCss(join(stylesDirectory, '../../../AgentTaskResult/src/styles/theme.css'))).toContain("@import '../../../shared/theme-layout-tokens.css';")
  })
})
