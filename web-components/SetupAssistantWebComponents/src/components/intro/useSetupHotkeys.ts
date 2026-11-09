import { useCallback, useEffect, useRef, useState } from 'react'

import {
  applySetupHotkey,
  cancelSetupHotkeyCapture,
  captureSetupHotkey,
  evaluateSetupHotkeys,
  isSetupNativeBridgeAvailable,
} from '@/services/bridge'

import {
  parseApplyOutcome,
  parseCaptured,
  parseEvaluation,
  type HotkeyConflict,
  type HotkeyRowEvaluation,
  type NativeHotkeyBinding,
} from './hotkeyAlternatives'

export type HotkeyLoadStatus = 'loading' | 'ready' | 'unavailable'

export type HotkeyRowPhase =
  | { kind: 'idle' }
  | { kind: 'working' }
  | { kind: 'capturing' }
  | { kind: 'blocked', binding: NativeHotkeyBinding, conflicts: HotkeyConflict[] }
  | { kind: 'failed', message: string }
  | { kind: 'changed', binding: NativeHotkeyBinding }
  | { kind: 'kept' }

/** What the person decided for one hotkey on the express confirm screen. Nothing is saved until Do it, so these are held here and applied together. */
export type StagedHotkeyChoice =
  | { kind: 'binding', binding: NativeHotkeyBinding, acknowledged: boolean }
  | { kind: 'keep' }

export interface UseSetupHotkeysOptions {
  /** Check keys without saving them and hold the person's choices in `choices`, instead of saving each choice at once. */
  staged?: boolean
}

export const CAPTURE_TIMEOUT_MESSAGE = 'I stopped listening because no keys were pressed. Choose different keys to try again.'
export const SAVE_FAILED_MESSAGE = "I couldn't save that hotkey. You can change it in Settings, Hotkeys."

const IDLE: HotkeyRowPhase = { kind: 'idle' }
const BRIDGE_TIMEOUT_PREFIX = "Setup action '"

function messageOf(error: unknown): string {
  return error instanceof Error && error.message ? error.message : SAVE_FAILED_MESSAGE
}

function isBridgeTimeout(error: unknown): boolean {
  return error instanceof Error && error.message.startsWith(BRIDGE_TIMEOUT_PREFIX)
}

/** Loads the person's hotkeys with their clashes and proposed replacements, and runs the one-click, record-your-own and keep-mine actions for each row. With `staged`, the actions only check the keys and hold the choice for the express confirm screen. */
export function useSetupHotkeys({ staged = false }: UseSetupHotkeysOptions = {}) {
  const [status, setStatus] = useState<HotkeyLoadStatus>(() => (isSetupNativeBridgeAvailable() ? 'loading' : 'unavailable'))
  const [rows, setRows] = useState<HotkeyRowEvaluation[]>([])
  const [phases, setPhases] = useState<Record<string, HotkeyRowPhase>>({})
  const [choices, setChoices] = useState<Record<string, StagedHotkeyChoice>>({})
  const isMountedRef = useRef(true)
  const capturingRef = useRef<Set<string>>(new Set())
  const tokensRef = useRef<Record<string, number>>({})
  // The rows as the Mac reported them, so a staged choice can be undone.
  const loadedRowsRef = useRef<HotkeyRowEvaluation[]>([])

  const setPhase = useCallback((id: string, phase: HotkeyRowPhase) => {
    if (isMountedRef.current) setPhases(previous => ({ ...previous, [id]: phase }))
  }, [])

  useEffect(() => {
    isMountedRef.current = true
    if (isSetupNativeBridgeAvailable()) {
      evaluateSetupHotkeys()
        .then((result) => {
          if (!isMountedRef.current) return
          const parsed = parseEvaluation(result.resultPayload)
          if (parsed) {
            loadedRowsRef.current = parsed
            setRows(parsed)
            setStatus('ready')
          } else {
            setStatus('unavailable')
          }
        })
        .catch(() => {
          if (isMountedRef.current) setStatus('unavailable')
        })
    }
    const capturing = capturingRef.current
    return () => {
      isMountedRef.current = false
      if (capturing.size > 0) {
        cancelSetupHotkeyCapture()
        capturing.clear()
      }
    }
  }, [])

  const save = useCallback(async (id: string, binding: NativeHotkeyBinding, acknowledgeConflict: boolean, acknowledgedConflicts: HotkeyConflict[] = []) => {
    setPhase(id, { kind: 'working' })
    try {
      const result = staged
        ? await applySetupHotkey(id, binding, acknowledgeConflict, true)
        : await applySetupHotkey(id, binding, acknowledgeConflict)
      const outcome = parseApplyOutcome(result.resultPayload)
      if (!outcome) {
        setPhase(id, { kind: 'failed', message: SAVE_FAILED_MESSAGE })
        return
      }
      if (outcome.saved) {
        if (isMountedRef.current) {
          if (staged) {
            // The row shows the chosen keys, and keeps the clashes the person accepted so the status can say so.
            setRows(previous => previous.map(row => (
              row.id === id ? { ...row, binding, conflicts: acknowledgeConflict ? acknowledgedConflicts : [], alternative: null } : row
            )))
            setChoices(previous => ({ ...previous, [id]: { kind: 'binding', binding, acknowledged: acknowledgeConflict } }))
          } else {
            setRows(outcome.rows)
          }
        }
        setPhase(id, { kind: 'changed', binding })
      } else {
        setPhase(id, { kind: 'blocked', binding, conflicts: outcome.conflicts })
      }
    } catch (error) {
      setPhase(id, { kind: 'failed', message: messageOf(error) })
    }
  }, [setPhase, staged])

  const applyAlternative = useCallback((id: string) => {
    const alternative = rows.find(row => row.id === id)?.alternative
    if (alternative) void save(id, alternative, false)
  }, [rows, save])

  const startCapture = useCallback(async (id: string) => {
    const token = (tokensRef.current[id] ?? 0) + 1
    tokensRef.current[id] = token
    capturingRef.current.add(id)
    setPhase(id, { kind: 'capturing' })
    try {
      const result = await captureSetupHotkey(id)
      if (tokensRef.current[id] !== token) return
      capturingRef.current.delete(id)
      const captured = parseCaptured(result.resultPayload)
      if (!captured) {
        setPhase(id, IDLE)
        return
      }
      await save(id, captured, false)
    } catch (error) {
      if (tokensRef.current[id] !== token) return
      capturingRef.current.delete(id)
      if (isBridgeTimeout(error)) {
        cancelSetupHotkeyCapture()
        setPhase(id, { kind: 'failed', message: CAPTURE_TIMEOUT_MESSAGE })
      } else {
        setPhase(id, { kind: 'failed', message: messageOf(error) })
      }
    }
  }, [save, setPhase])

  const cancelCapture = useCallback((id: string) => {
    tokensRef.current[id] = (tokensRef.current[id] ?? 0) + 1
    capturingRef.current.delete(id)
    cancelSetupHotkeyCapture()
    setPhase(id, IDLE)
  }, [setPhase])

  const acceptBlocked = useCallback((id: string) => {
    const phase = phases[id]
    if (phase?.kind === 'blocked') void save(id, phase.binding, true, phase.conflicts)
  }, [phases, save])

  const keepCurrent = useCallback((id: string) => {
    if (staged) setChoices(previous => ({ ...previous, [id]: { kind: 'keep' } }))
    setPhase(id, { kind: 'kept' })
  }, [setPhase, staged])

  /** Drops a staged choice and shows the hotkey as it is on this Mac again. Only meaningful when staged. */
  const resetChoice = useCallback((id: string) => {
    const original = loadedRowsRef.current.find(row => row.id === id)
    if (original) setRows(previous => previous.map(row => (row.id === id ? original : row)))
    setChoices(previous => {
      const next = { ...previous }
      delete next[id]
      return next
    })
    setPhase(id, IDLE)
  }, [setPhase])

  return { status, rows, phases, choices, resetChoice, applyAlternative, startCapture, cancelCapture, acceptBlocked, keepCurrent }
}
