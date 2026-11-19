import { describe, expect, it } from 'vitest'
import { broadWhitelistCommandName } from './whitelistPatternBreadth'

describe('broadWhitelistCommandName', () => {
  it('names the tool when a prefix pattern is only the command name', () => {
    expect(broadWhitelistCommandName({ pattern: 'gh', patternType: 'prefix' })).toBe('gh')
    expect(broadWhitelistCommandName({ pattern: '  git ', patternType: 'prefix' })).toBe('git')
  })

  it('does not flag a pattern that names more than the command', () => {
    expect(broadWhitelistCommandName({ pattern: 'gh gist view', patternType: 'prefix' })).toBeNull()
    expect(broadWhitelistCommandName({ pattern: 'git status', patternType: 'prefix' })).toBeNull()
  })

  it('does not flag exact or regex patterns', () => {
    expect(broadWhitelistCommandName({ pattern: 'gh', patternType: 'exact' })).toBeNull()
    expect(broadWhitelistCommandName({ pattern: '^gh .*', patternType: 'regex' })).toBeNull()
  })

  it('looks through the wrapper that older versions stored in front of the command', () => {
    expect(broadWhitelistCommandName({ pattern: 'bash -lc gh', patternType: 'prefix' })).toBe('gh')
    expect(broadWhitelistCommandName({ pattern: 'bash -lc gh gist view', patternType: 'prefix' })).toBeNull()
    expect(broadWhitelistCommandName({ pattern: 'bash', patternType: 'prefix' })).toBeNull()
  })

  it('ignores an empty pattern', () => {
    expect(broadWhitelistCommandName({ pattern: '   ', patternType: 'prefix' })).toBeNull()
  })
})
