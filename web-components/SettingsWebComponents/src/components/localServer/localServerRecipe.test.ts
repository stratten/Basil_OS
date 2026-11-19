import { describe, expect, it } from 'vitest'
import { EMPTY_LOCAL_SERVER_FORM, buildLocalServerRegistration, parseRecipe, type LocalServerFormValues } from './localServerForm'

const INSTALL = { requirements: [], artifacts: [{ name: 'Bridge', expects: 'bin/bridge', methods: [{ kind: 'download', url: 'https://example.test/bridge', sha256: 'a'.repeat(64) }] }] }
const PROBE = { url: 'http://127.0.0.1:{port}/status', auth: 'none', state_path: 'state', states: { ok: 'ready' } }

function form(overrides: Partial<LocalServerFormValues>): LocalServerFormValues {
  return { ...EMPTY_LOCAL_SERVER_FORM, name: 'Bridge', command: '/usr/bin/env', ...overrides }
}

describe('parseRecipe', () => {
  it('treats an empty box as no recipe', () => {
    expect(parseRecipe('  \n ')).toEqual({ ok: true, value: {} })
  })

  it('reads the install and probe parts', () => {
    expect(parseRecipe(JSON.stringify({ install: INSTALL, probe: PROBE }))).toEqual({ ok: true, value: { install: INSTALL, probe: PROBE } })
  })

  it.each([
    ['{not json', 'not valid JSON'],
    ['[1, 2]', 'must be a JSON object'],
    ['"text"', 'must be a JSON object'],
    ['{"install": []}', '"install" part of the recipe must be an object'],
    ['{"probe": "x"}', '"probe" part of the recipe must be an object'],
    ['{"install": {}, "extra": 1}', 'unknown part: extra'],
  ])('refuses %s', (text, fragment) => {
    const parsed = parseRecipe(text)

    expect(parsed.ok).toBe(false)
    if (!parsed.ok) expect(parsed.error).toContain(fragment)
  })
})

describe('buildLocalServerRegistration with a recipe', () => {
  it('sends the install recipe and attaches the probe to the background program', () => {
    const built = buildLocalServerRegistration(
      form({ useCompanion: true, companionCommand: '{install_dir}/bin/bridge', companionArgsText: '{port}', recipeText: JSON.stringify({ install: INSTALL, probe: PROBE }) }),
    )

    expect(built.ok).toBe(true)
    if (built.ok) {
      expect(built.value.install).toEqual(INSTALL)
      expect(built.value.companion?.probe).toEqual(PROBE)
    }
  })

  it('leaves both out when no recipe is pasted', () => {
    const built = buildLocalServerRegistration(form({ useCompanion: true, companionCommand: '/usr/bin/true' }))

    expect(built.ok).toBe(true)
    if (built.ok) {
      expect('install' in built.value).toBe(false)
      expect(built.value.companion && 'probe' in built.value.companion).toBe(false)
    }
  })

  it('refuses a status page when there is no background program to read it from', () => {
    const built = buildLocalServerRegistration(form({ recipeText: JSON.stringify({ probe: PROBE }) }))

    expect(built.ok).toBe(false)
    if (!built.ok) expect(built.error).toContain('belongs to a background program')
  })

  it('reports a broken recipe before anything is sent', () => {
    const built = buildLocalServerRegistration(form({ recipeText: '{oops' }))

    expect(built).toEqual({ ok: false, error: 'The setup recipe is not valid JSON.' })
  })
})
