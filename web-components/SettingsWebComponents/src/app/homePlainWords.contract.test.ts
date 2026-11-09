// @vitest-environment node

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

function read(relativeToThisFile: string): string {
  return readFileSync(fileURLToPath(new URL(relativeToThisFile, import.meta.url)), 'utf8')
}

const HOME_FILES = ['./HomeSettingsApp.tsx', './homePresets.ts']

const DEVELOPER_PHRASES = [
  'capture scheduler',
  'its backend',
  'start the monitor',
  'hotkey monitoring',
  'local capture records',
  'voice-driven workflows',
]

describe('Home settings wording', () => {
  it.each(HOME_FILES)('%s has none of the developer-only phrases', (file) => {
    const source = read(file).toLowerCase()
    for (const phrase of DEVELOPER_PHRASES) {
      expect(source, `"${phrase}" should not appear in ${file}`).not.toContain(phrase)
    }
  })
})
