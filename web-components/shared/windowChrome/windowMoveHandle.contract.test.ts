// @vitest-environment node

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const css = readFileSync(fileURLToPath(new URL('./window-move-handle.css', import.meta.url)), 'utf8')
const webComponentsRoot = fileURLToPath(new URL('../..', import.meta.url))

function rule(selector: string): string {
  const escaped = selector.replace(/[.>]/g, match => `\\${match}`)
  const match = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))
  expect(match, `${selector} rule`).not.toBeNull()
  return match?.[1] ?? ''
}

function sourceFiles(directory: string, found: string[] = []): string[] {
  for (const name of readdirSync(directory)) {
    if (name === 'node_modules' || name === 'dist' || name.startsWith('.')) continue
    const path = join(directory, name)
    if (statSync(path).isDirectory()) {
      sourceFiles(path, found)
    } else if (name.endsWith('.tsx') && !name.endsWith('.test.tsx')) {
      found.push(path)
    }
  }
  return found
}

/** Every window header that the native drag area lets you drag shows the grip. The decision toast without a header, the compact Model Downloads panel whose title is centered where the grip sits, the checklist overlay, the tray, and modals are not draggable windows with a header and are left out. */
const SURFACES_WITH_THE_GRIP = [
  'AgentTaskCaptureInput/src/components/CaptureHeader.tsx',
  'AgentTaskResult/src/components/FilePreviewApp.tsx',
  'AgentTaskResult/src/components/header/Header.tsx',
  'AgentTaskResult/src/components/localWebPreview/LocalWebPreviewApp.tsx',
  'AmbientSuggestionsPanel/src/App.tsx',
  'AssistantSession/src/app/AssistantOutputHistoryApp.tsx',
  'AssistantSession/src/components/Header.tsx',
  'BasilBoard/src/shell/BoardChrome.tsx',
  'BasilBoard/src/shell/DetachedCapabilityShell.tsx',
  'BasilBoard/src/standalone/ConversationWindowChrome.tsx',
  'MeetingAssistant/src/components/WindowChrome.tsx',
  'MeetingDetectedMiniPanel/src/App.tsx',
  'PowerUserGuidePanel/src/App.tsx',
  'ProfileMemorySkillsEditor/src/app/ProfileEditorApp.tsx',
  'ScheduledRunMiniPanel/src/App.tsx',
  'SkillReconciliationWorkspace/src/components/Header.tsx',
  'TranscriptionWidget/src/components/FullWidget.tsx',
  'shared/windowChrome/BasilWindowChrome.tsx',
]

describe('window-move-handle.css', () => {
  it('is invisible until the header is hovered or holds focus, the way Pause and Stop are', () => {
    expect(rule('.window-move-handle')).toContain('opacity: 0')
    expect(css).toMatch(/\.window-move-host:hover > \.window-move-handle,\s*\.window-move-host:focus-within > \.window-move-handle\s*\{[^}]*opacity: 1/)
  })

  it('only advertises the drag area: no pointer events, and it keeps its space so the title does not shift', () => {
    const handle = rule('.window-move-handle')
    expect(handle).toContain('pointer-events: none')
    expect(handle).toContain('position: absolute')
    expect(handle).not.toContain('display: none')
  })

  it('positions the grip against the header it sits in', () => {
    expect(rule('.window-move-host')).toContain('position: relative')
  })

  it('is two plain hairlines, with no border, background or dots on the handle itself', () => {
    const handle = rule('.window-move-handle')
    expect(handle).not.toMatch(/(^|[;\s])border\s*:/)
    expect(handle).not.toMatch(/(^|[;\s])background\s*:/)
    expect(handle).not.toContain('radial-gradient')
    const line = rule('.window-move-handle i')
    expect(line).toContain('height: 1px')
    expect(line).toContain('background: var(--text-secondary)')
  })
})

describe('surfaces that show the grip', () => {
  const files = sourceFiles(webComponentsRoot).filter(file => !file.endsWith('windowChrome/WindowMoveHandle.tsx'))
  const users = files.filter(file => readFileSync(file, 'utf8').includes('<WindowMoveHandle'))

  it('are exactly the draggable window headers listed here', () => {
    expect(users.map(file => relative(webComponentsRoot, file)).sort()).toEqual([...SURFACES_WITH_THE_GRIP].sort())
  })

  it('mark the header they draw it in as the host the grip positions itself against', () => {
    for (const file of users) {
      expect(readFileSync(file, 'utf8'), relative(webComponentsRoot, file)).toContain('window-move-host')
    }
  })

  it('put the grip first in the header, so it never shifts the title', () => {
    for (const file of users) {
      expect(readFileSync(file, 'utf8'), relative(webComponentsRoot, file)).toMatch(/window-move-host[^\n]*>\n\s*<WindowMoveHandle \/>/)
    }
  })
})
