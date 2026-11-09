import type { WhitelistPatternFields } from '../types'

const SHELL_WRAPPERS = new Set(['bash', 'sh', 'zsh', 'fish', 'dash', 'ksh'])

/** The words a stored prefix pattern requires. Patterns saved by older versions may still carry the wrapper in front of the command (`bash -lc gh`); it is dropped, as the backend does when matching. */
function requiredWords(pattern: string): string[] {
  const words = pattern.trim().split(/\s+/).filter(Boolean)
  const executable = (words[0] ?? '').split('/').pop()?.toLowerCase().replace(/[\d.]+$/, '') ?? ''
  if (!SHELL_WRAPPERS.has(executable)) return words
  for (let index = 1; index < words.length; index += 1) {
    const word = words[index]
    if (word.startsWith('-') && !word.startsWith('--') && word.slice(1).includes('c')) return words.slice(index + 1)
    if (!word.startsWith('-')) return []
  }
  return []
}

/**
 * The command name a stored pattern approves on its own, or null when the pattern names more than the command.
 * A single-word prefix pattern such as `gh` approves every use of that tool, so settings flags it; a pattern such as `gh gist view` does not.
 */
export function broadWhitelistCommandName(pattern: Pick<WhitelistPatternFields, 'pattern' | 'patternType'>): string | null {
  if (pattern.patternType !== 'prefix') return null
  const words = requiredWords(pattern.pattern)
  return words.length === 1 ? words[0] : null
}
