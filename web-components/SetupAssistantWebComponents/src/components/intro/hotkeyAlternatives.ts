import type { SetupHotkeyBindingPayload } from '@/services/bridge'

import { describeHotkeyBinding, SETUP_HOTKEY_ROWS } from './hotkeyDisplay'

export type NativeHotkeyBinding = SetupHotkeyBindingPayload

export type HotkeyConflictKind = 'mac_shortcut' | 'media_key' | 'basil_duplicate'

export interface HotkeyConflict {
  hotkeyId: string
  kind: HotkeyConflictKind
  source: string
  certainty: 'exact' | 'possible'
  message: string
}

export interface HotkeyRowEvaluation {
  id: string
  binding: NativeHotkeyBinding
  conflicts: HotkeyConflict[]
  alternative: NativeHotkeyBinding | null
}

export interface HotkeyApplyOutcome {
  saved: boolean
  conflicts: HotkeyConflict[]
  rows: HotkeyRowEvaluation[]
}

export interface HotkeyChange {
  id: string
  title: string
  from: NativeHotkeyBinding
  to: NativeHotkeyBinding
  reason: string
}

export interface HotkeyUnresolved {
  id: string
  title: string
  message: string
}

export interface HotkeyResolution {
  changes: HotkeyChange[]
  unresolved: HotkeyUnresolved[]
}

type Payload = Record<string, unknown> | undefined

const CONFLICT_KINDS: readonly string[] = ['mac_shortcut', 'media_key', 'basil_duplicate']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseBinding(value: unknown): NativeHotkeyBinding | null {
  if (!isRecord(value)) return null
  const { key, modifiers } = value
  if (typeof key !== 'string') return null
  if (!Array.isArray(modifiers) || !modifiers.every(item => typeof item === 'string')) return null
  return {
    key,
    enabled: value.enabled !== false,
    modifiers: modifiers as string[],
    isDoublePress: value.isDoublePress === true,
    doublePressKey: typeof value.doublePressKey === 'string' ? value.doublePressKey : null,
  }
}

function parseConflict(value: unknown): HotkeyConflict | null {
  if (!isRecord(value)) return null
  const { hotkeyId, kind, source, certainty, message } = value
  if (typeof hotkeyId !== 'string' || typeof source !== 'string' || typeof message !== 'string') return null
  if (typeof kind !== 'string' || !CONFLICT_KINDS.includes(kind)) return null
  if (certainty !== 'exact' && certainty !== 'possible') return null
  return { hotkeyId, kind: kind as HotkeyConflictKind, source, certainty, message }
}

function parseConflicts(value: unknown): HotkeyConflict[] {
  if (!Array.isArray(value)) return []
  return value.map(parseConflict).filter((conflict): conflict is HotkeyConflict => conflict !== null)
}

export function parseRows(value: unknown): HotkeyRowEvaluation[] | null {
  if (!Array.isArray(value)) return null
  const rows: HotkeyRowEvaluation[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item.id !== 'string') continue
    const binding = parseBinding(item.binding)
    if (!binding) continue
    rows.push({
      id: item.id,
      binding,
      conflicts: parseConflicts(item.conflicts),
      alternative: parseBinding(item.alternative),
    })
  }
  return rows.length > 0 ? rows : null
}

export function parseEvaluation(payload: Payload): HotkeyRowEvaluation[] | null {
  return parseRows(payload?.rows)
}

export function parseApplyOutcome(payload: Payload): HotkeyApplyOutcome | null {
  if (!payload || typeof payload.saved !== 'boolean') return null
  const rows = parseRows(payload.rows)
  if (!rows) return null
  return { saved: payload.saved, conflicts: parseConflicts(payload.conflicts), rows }
}

/** The keys the person pressed, or null when the recording was canceled or the answer is malformed. */
export function parseCaptured(payload: Payload): NativeHotkeyBinding | null {
  if (payload?.captured !== true) return null
  return parseBinding(payload.binding)
}

export function parseResolution(payload: Payload): HotkeyResolution | null {
  if (!payload || !Array.isArray(payload.changes) || !Array.isArray(payload.unresolved)) return null
  const changes: HotkeyChange[] = []
  for (const item of payload.changes) {
    if (!isRecord(item)) continue
    const from = parseBinding(item.from)
    const to = parseBinding(item.to)
    if (typeof item.id !== 'string' || typeof item.title !== 'string' || typeof item.reason !== 'string' || !from || !to) continue
    changes.push({ id: item.id, title: item.title, from, to, reason: item.reason })
  }
  const unresolved: HotkeyUnresolved[] = []
  for (const item of payload.unresolved) {
    if (!isRecord(item)) continue
    if (typeof item.id !== 'string' || typeof item.title !== 'string' || typeof item.message !== 'string') continue
    unresolved.push({ id: item.id, title: item.title, message: item.message })
  }
  return { changes, unresolved }
}

/** The keys as they are written on the Hotkeys page, for example "⌥␣", or null when the binding is off or empty. */
export function describeNativeBinding(binding: NativeHotkeyBinding | null | undefined): string | null {
  if (!binding) return null
  return describeHotkeyBinding({
    key: binding.key,
    enabled: binding.enabled,
    modifiers: binding.modifiers,
    is_double_press: binding.isDoublePress,
    double_press_key: binding.doublePressKey,
  })
}

/** The title setup uses for a hotkey row, falling back to the native title for an unknown id. */
export function hotkeyRowTitle(id: string, fallback: string): string {
  return SETUP_HOTKEY_ROWS.find(row => row.id === id)?.title ?? fallback
}

/** What express setup tells the person after it fixed, or found nothing to fix in, their hotkeys. */
export function describeResolution(result: HotkeyResolution): { outcome: 'applied' | 'skipped'; message: string } {
  const sentences: string[] = []
  for (const change of result.changes) {
    const from = describeNativeBinding(change.from) ?? 'its old keys'
    const to = describeNativeBinding(change.to) ?? 'new keys'
    sentences.push(`I switched ${hotkeyRowTitle(change.id, change.title)} from ${from} to ${to}, because the old keys clashed with ${change.reason}.`)
  }
  for (const item of result.unresolved) {
    sentences.push(`I couldn't find a free shortcut for ${hotkeyRowTitle(item.id, item.title)}, so I left it as it is.`)
  }
  if (sentences.length === 0) {
    return { outcome: 'applied', message: 'None of your hotkeys clash with anything on this Mac, so I left them alone.' }
  }
  sentences.push('You can change any hotkey in Settings, Hotkeys.')
  return { outcome: result.changes.length > 0 ? 'applied' : 'skipped', message: sentences.join(' ') }
}
