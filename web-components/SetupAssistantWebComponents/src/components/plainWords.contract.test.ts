// @vitest-environment node

import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const DIRECTORIES = ['./intro/', './express/', './permissions/', './layout/']

// Phrases only the developers use, or that an earlier version of setup used. Matching is case-insensitive.
const DEVELOPER_PHRASES = [
  'reasoning route',
  'reasoning during setup',
  'setup reasoning preference',
  'two routes above',
  'simulate keystrokes',
  'modifier gestures',
  'paprika tasks',
  'personal-profile',
  'named skills',
  'provider you choose',
  'local on this machine',
  'leaves this machine',
]

function sourceFiles(directory: string): string[] {
  const absolute = fileURLToPath(new URL(directory, import.meta.url))
  return readdirSync(absolute)
    .filter(name => /\.(ts|tsx)$/.test(name) && !/\.(test|spec)\./.test(name))
    .map(name => `${directory}${name}`)
}

function read(relativeToThisFile: string): string {
  return readFileSync(fileURLToPath(new URL(relativeToThisFile, import.meta.url)), 'utf8')
}

describe('setup wording', () => {
  it.each(DIRECTORIES)('%s has at least one source file for the guard to read', (directory) => {
    expect(sourceFiles(directory).length).toBeGreaterThan(0)
  })

  it.each(DIRECTORIES.flatMap(sourceFiles))('%s has none of the developer-only phrases', (file) => {
    const source = read(file).toLowerCase()
    for (const phrase of DEVELOPER_PHRASES) {
      expect(source, `"${phrase}" should not appear in ${file}`).not.toContain(phrase)
    }
  })
})
