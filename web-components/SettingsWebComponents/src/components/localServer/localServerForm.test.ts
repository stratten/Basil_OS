import { describe, expect, it } from 'vitest'
import {
  EMPTY_LOCAL_SERVER_FORM,
  buildLocalServerRegistration,
  namesMissingValues,
  parseEnvLines,
  parseSecretNames,
  secretNamesInForm,
  secretValuesFor,
  splitLines,
  type LocalServerFormValues,
} from './localServerForm'

function form(overrides: Partial<LocalServerFormValues> = {}): LocalServerFormValues {
  return { ...EMPTY_LOCAL_SERVER_FORM, name: 'Example', command: '/usr/bin/env', ...overrides }
}

describe('splitLines', () => {
  it('keeps one trimmed item per non-blank line and keeps an argument that contains spaces whole', () => {
    expect(splitLines('  run  \r\n\r\n--name=two words\n   \nlast')).toEqual(['run', '--name=two words', 'last'])
  })
})

describe('parseEnvLines', () => {
  it('reads NAME=value lines, keeps an equals sign inside a value, and allows an empty value', () => {
    expect(parseEnvLines('MODE=local\nURL=http://a/?x=1\nEMPTY=\n', 'Settings')).toEqual({
      ok: true,
      value: { MODE: 'local', URL: 'http://a/?x=1', EMPTY: '' },
    })
  })

  it.each(['no equals sign', '=value', '1BAD=x', 'HAS SPACE=x', `${'N'.repeat(65)}=x`])('refuses the line %s and says which line', (line) => {
    const result = parseEnvLines(`GOOD=1\n${line}`, 'Settings')
    expect(result.ok).toBe(false)
    expect(!result.ok && result.error).toContain('Settings, line 2')
  })

  it('refuses a name listed twice, including a name that is also an object property', () => {
    expect(parseEnvLines('A=1\nA=2', 'Settings')).toEqual({ ok: false, error: 'Settings: A is listed twice.' })
    expect(parseEnvLines('constructor=1\nconstructor=2', 'Settings').ok).toBe(false)
    expect(parseEnvLines('__proto__=1', 'Settings')).toEqual({ ok: true, value: JSON.parse('{"__proto__":"1"}') })
  })
})

describe('parseSecretNames', () => {
  it('accepts names separated by commas, spaces and new lines', () => {
    expect(parseSecretNames('API_KEY, BRIDGE_TOKEN\nOTHER', 'Secrets')).toEqual({ ok: true, value: ['API_KEY', 'BRIDGE_TOKEN', 'OTHER'] })
    expect(parseSecretNames('   ', 'Secrets')).toEqual({ ok: true, value: [] })
  })

  it('refuses an invalid name, a repeated name, and more than sixteen names', () => {
    expect(parseSecretNames('1BAD', 'Secrets').ok).toBe(false)
    expect(parseSecretNames('A,B,A', 'Secrets')).toEqual({ ok: false, error: 'Secrets: A is listed twice.' })
    const seventeen = Array.from({ length: 17 }, (_, index) => `NAME_${index}`).join(',')
    expect(parseSecretNames(seventeen, 'Secrets')).toEqual({ ok: false, error: 'Secrets: a server can declare at most 16 secrets.' })
  })
})

describe('buildLocalServerRegistration', () => {
  it('builds a minimal server with empty defaults and no background program', () => {
    expect(buildLocalServerRegistration(form())).toEqual({
      ok: true,
      value: {
        friendlyName: 'Example',
        description: undefined,
        command: '/usr/bin/env',
        args: [],
        cwd: undefined,
        env: {},
        secretEnv: [],
        sourceUrl: undefined,
        companion: null,
      },
    })
  })

  it('shapes every field of a server with a background program', () => {
    const result = buildLocalServerRegistration(
      form({
        name: '  Bridge  ',
        description: ' Local bridge ',
        argsText: 'run\n--port={port}',
        folder: ' /Users/me/bridge ',
        envText: 'PORT={port}',
        secretNamesText: 'API_KEY',
        sourceUrl: ' https://example.com/readme ',
        useCompanion: true,
        companionCommand: ' /usr/local/bin/go ',
        companionArgsText: 'run\n.\n{port}',
        companionFolder: '/Users/me/bridge/server',
        companionEnvText: 'LOG=debug',
        companionSecretNamesText: 'BRIDGE_TOKEN',
        startWithBasil: false,
        fixedPortText: '',
      }),
    )

    expect(result).toEqual({
      ok: true,
      value: {
        friendlyName: 'Bridge',
        description: 'Local bridge',
        command: '/usr/bin/env',
        args: ['run', '--port={port}'],
        cwd: '/Users/me/bridge',
        env: { PORT: '{port}' },
        secretEnv: ['API_KEY'],
        sourceUrl: 'https://example.com/readme',
        companion: {
          command: '/usr/local/bin/go',
          args: ['run', '.', '{port}'],
          cwd: '/Users/me/bridge/server',
          env: { LOG: 'debug' },
          secretEnv: ['BRIDGE_TOKEN'],
          startWithBasil: false,
          fixedPort: undefined,
        },
      },
    })
  })

  it('ignores the background program fields when the box is not ticked', () => {
    const result = buildLocalServerRegistration(form({ companionCommand: '', companionEnvText: 'not valid at all', fixedPortText: 'abc' }))
    expect(result.ok && result.value.companion).toBeNull()
  })

  it.each([
    [{ name: '   ' }, 'Enter a name for the server.'],
    [{ command: '  ' }, 'Enter the command that starts the server.'],
    [{ envText: 'oops' }, 'Settings, line 1'],
    [{ secretNamesText: '9X' }, 'Secrets:'],
    [{ envText: 'API_KEY=x', secretNamesText: 'API_KEY' }, 'API_KEY is listed both as a setting and as a secret'],
    [{ useCompanion: true }, 'Enter the command that starts the background program.'],
    [{ useCompanion: true, companionCommand: 'x', companionEnvText: 'bad' }, 'Background program settings, line 1'],
    [{ useCompanion: true, companionCommand: 'x', companionSecretNamesText: 'a b a' }, 'Background program secrets: a is listed twice.'],
    [{ useCompanion: true, companionCommand: 'x', companionEnvText: 'T=1', companionSecretNamesText: 'T' }, 'Background program: T is listed both'],
    [{ useCompanion: true, companionCommand: 'x', fixedPortText: '0' }, 'port must be a whole number from 1 to 65535'],
    [{ useCompanion: true, companionCommand: 'x', fixedPortText: '70000' }, 'port must be a whole number from 1 to 65535'],
    [{ useCompanion: true, companionCommand: 'x', fixedPortText: '80.5' }, 'port must be a whole number from 1 to 65535'],
    [{ useCompanion: true, companionCommand: 'x', fixedPortText: '-3' }, 'port must be a whole number from 1 to 65535'],
  ] as Array<[Partial<LocalServerFormValues>, string]>)('refuses %j', (overrides, message) => {
    const result = buildLocalServerRegistration(form(overrides))
    expect(result.ok).toBe(false)
    expect(!result.ok && result.error).toContain(message)
  })

  it('accepts a fixed port inside the range', () => {
    const result = buildLocalServerRegistration(form({ useCompanion: true, companionCommand: 'x', fixedPortText: ' 8080 ' }))
    expect(result.ok && result.value.companion?.fixedPort).toBe(8080)
  })
})

describe('secret values', () => {
  it('lists each valid name once, the server first, and skips a half-typed invalid name', () => {
    const names = secretNamesInForm(form({ secretNamesText: 'API_KEY, 9bad, SHARED', useCompanion: true, companionSecretNamesText: 'SHARED BRIDGE_TOKEN' }))
    expect(names).toEqual(['API_KEY', 'SHARED', 'BRIDGE_TOKEN'])
  })

  it('does not list the background program names while that box is not ticked', () => {
    expect(secretNamesInForm(form({ secretNamesText: 'A', companionSecretNamesText: 'B' }))).toEqual(['A'])
  })

  it('trims values, drops blanks and names that are not asked for, and reports what is still missing', () => {
    expect(secretValuesFor(['A', 'B', 'C'], { A: '  k-1  ', B: '   ', Z: 'unrelated' })).toEqual({ A: 'k-1' })
    expect(namesMissingValues(['A', 'B', 'C'], { A: 'k-1', B: '   ' })).toEqual(['B', 'C'])
  })
})
