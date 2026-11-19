import type { LocalServerCompanionRegistration, LocalServerRegistration } from '../../types'

const VARIABLE_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
export const MAX_SECRET_NAMES = 16
export const MAX_VARIABLE_NAME_LENGTH = 64

export interface LocalServerFormValues {
  name: string
  description: string
  command: string
  argsText: string
  folder: string
  envText: string
  secretNamesText: string
  sourceUrl: string
  useCompanion: boolean
  companionCommand: string
  companionArgsText: string
  companionFolder: string
  companionEnvText: string
  companionSecretNamesText: string
  startWithBasil: boolean
  fixedPortText: string
  recipeText: string
}

export const EMPTY_LOCAL_SERVER_FORM: LocalServerFormValues = {
  name: '',
  description: '',
  command: '',
  argsText: '',
  folder: '',
  envText: '',
  secretNamesText: '',
  sourceUrl: '',
  useCompanion: false,
  companionCommand: '',
  companionArgsText: '',
  companionFolder: '',
  companionEnvText: '',
  companionSecretNamesText: '',
  startWithBasil: true,
  fixedPortText: '',
  recipeText: '',
}

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string }

function success<T>(value: T): Parsed<T> {
  return { ok: true, value }
}

function failure<T>(error: string): Parsed<T> {
  return { ok: false, error }
}

/** One item per non-blank line, each trimmed. */
export function splitLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function optionalText(text: string): string | undefined {
  const trimmed = text.trim()
  return trimmed.length > 0 ? trimmed : undefined
}

function isValidVariableName(name: string): boolean {
  return name.length <= MAX_VARIABLE_NAME_LENGTH && VARIABLE_NAME.test(name)
}

/** Parses `NAME=value` lines. `label` names the box in any error message. */
export function parseEnvLines(text: string, label: string): Parsed<Record<string, string>> {
  const entries = new Map<string, string>()
  const lines = text.split(/\r?\n/)
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.trim().length === 0) continue
    const separator = line.indexOf('=')
    const name = separator > 0 ? line.slice(0, separator).trim() : ''
    if (!isValidVariableName(name)) {
      return failure(`${label}, line ${index + 1}: write each setting as NAME=value, where NAME uses letters, digits and underscores.`)
    }
    if (entries.has(name)) return failure(`${label}: ${name} is listed twice.`)
    entries.set(name, line.slice(separator + 1).trim())
  }
  return success(Object.fromEntries(entries))
}

/** Parses secret variable names separated by commas, spaces or new lines. */
export function parseSecretNames(text: string, label: string): Parsed<string[]> {
  const names = text.split(/[\s,]+/).filter((name) => name.length > 0)
  const seen = new Set<string>()
  for (const name of names) {
    if (!isValidVariableName(name)) {
      return failure(`${label}: "${name}" is not a valid variable name. Use letters, digits and underscores, starting with a letter or underscore.`)
    }
    if (seen.has(name)) return failure(`${label}: ${name} is listed twice.`)
    seen.add(name)
  }
  if (names.length > MAX_SECRET_NAMES) return failure(`${label}: a server can declare at most ${MAX_SECRET_NAMES} secrets.`)
  return success(names)
}

function overlapMessage(env: Record<string, string>, secrets: string[], label: string): string | null {
  const clash = secrets.filter((name) => Object.prototype.hasOwnProperty.call(env, name))
  if (clash.length === 0) return null
  return `${label}: ${clash.join(', ')} is listed both as a setting and as a secret. Keep it only as a secret.`
}

function parseFixedPort(text: string): Parsed<number | undefined> {
  const trimmed = text.trim()
  if (trimmed.length === 0) return success(undefined)
  const port = /^\d+$/.test(trimmed) ? Number(trimmed) : Number.NaN
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return failure('The background program port must be a whole number from 1 to 65535.')
  }
  return success(port)
}

export interface PastedRecipe {
  install?: Record<string, unknown>
  probe?: Record<string, unknown>
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Reads the setup recipe the person pasted: a JSON object with an optional `install` recipe and an optional `probe` status page. Anything deeper is checked by the backend, which shows the person every address and command before anything runs. */
export function parseRecipe(text: string): Parsed<PastedRecipe> {
  const trimmed = text.trim()
  if (trimmed.length === 0) return success({})
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    return failure('The setup recipe is not valid JSON.')
  }
  if (!isPlainObject(parsed)) return failure('The setup recipe must be a JSON object with an "install" part, a "probe" part, or both.')
  const unknown = Object.keys(parsed).filter((key) => key !== 'install' && key !== 'probe')
  if (unknown.length > 0) return failure(`The setup recipe has an unknown part: ${unknown.join(', ')}. Use only "install" and "probe".`)
  if (parsed.install !== undefined && !isPlainObject(parsed.install)) return failure('The "install" part of the recipe must be an object.')
  if (parsed.probe !== undefined && !isPlainObject(parsed.probe)) return failure('The "probe" part of the recipe must be an object.')
  return success({ install: parsed.install as Record<string, unknown> | undefined, probe: parsed.probe as Record<string, unknown> | undefined })
}

function buildCompanion(form: LocalServerFormValues): Parsed<LocalServerCompanionRegistration> {
  const command = form.companionCommand.trim()
  if (command.length === 0) return failure('Enter the command that starts the background program.')
  const env = parseEnvLines(form.companionEnvText, 'Background program settings')
  if (!env.ok) return failure(env.error)
  const secrets = parseSecretNames(form.companionSecretNamesText, 'Background program secrets')
  if (!secrets.ok) return failure(secrets.error)
  const overlap = overlapMessage(env.value, secrets.value, 'Background program')
  if (overlap) return failure(overlap)
  const port = parseFixedPort(form.fixedPortText)
  if (!port.ok) return failure(port.error)
  return success({
    command,
    args: splitLines(form.companionArgsText),
    cwd: optionalText(form.companionFolder),
    env: env.value,
    secretEnv: secrets.value,
    startWithBasil: form.startWithBasil,
    fixedPort: port.value,
  })
}

/** The request the form sends, or the first problem found. Secret values are not part of it. */
export function buildLocalServerRegistration(form: LocalServerFormValues): Parsed<LocalServerRegistration> {
  const friendlyName = form.name.trim()
  if (friendlyName.length === 0) return failure('Enter a name for the server.')
  const command = form.command.trim()
  if (command.length === 0) return failure('Enter the command that starts the server.')
  const env = parseEnvLines(form.envText, 'Settings')
  if (!env.ok) return failure(env.error)
  const secrets = parseSecretNames(form.secretNamesText, 'Secrets')
  if (!secrets.ok) return failure(secrets.error)
  const overlap = overlapMessage(env.value, secrets.value, 'Settings')
  if (overlap) return failure(overlap)
  const recipe = parseRecipe(form.recipeText)
  if (!recipe.ok) return failure(recipe.error)
  let companion: LocalServerCompanionRegistration | null = null
  if (form.useCompanion) {
    const built = buildCompanion(form)
    if (!built.ok) return failure(built.error)
    companion = recipe.value.probe ? { ...built.value, probe: recipe.value.probe } : built.value
  } else if (recipe.value.probe) {
    return failure('A status page belongs to a background program. Tick "This server needs a background program running first" or remove the "probe" part of the recipe.')
  }
  return success({
    friendlyName,
    description: optionalText(form.description),
    command,
    args: splitLines(form.argsText),
    cwd: optionalText(form.folder),
    env: env.value,
    secretEnv: secrets.value,
    sourceUrl: optionalText(form.sourceUrl),
    companion,
    ...(recipe.value.install ? { install: recipe.value.install } : {}),
  })
}

/** Every valid secret name typed so far, the server's first and then the background program's, each once. Invalid fragments are skipped while the person is still typing. */
export function secretNamesInForm(form: LocalServerFormValues): string[] {
  const names: string[] = []
  const add = (text: string) => {
    for (const candidate of text.split(/[\s,]+/)) {
      if (candidate.length > 0 && isValidVariableName(candidate) && !names.includes(candidate)) names.push(candidate)
    }
  }
  add(form.secretNamesText)
  if (form.useCompanion) add(form.companionSecretNamesText)
  return names
}

/** The trimmed value for each of exactly these names. A name with no value is left out. */
export function secretValuesFor(names: readonly string[], values: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const name of names) {
    const value = (values[name] ?? '').trim()
    if (value.length > 0) result[name] = value
  }
  return result
}

/** The names that still have no value. */
export function namesMissingValues(names: readonly string[], values: Record<string, string>): string[] {
  return names.filter((name) => (values[name] ?? '').trim().length === 0)
}
