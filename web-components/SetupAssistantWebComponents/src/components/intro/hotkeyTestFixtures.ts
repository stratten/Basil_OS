import type { SetupBridgeActionResult } from '@/services/bridge'

import type { HotkeyConflict, HotkeyRowEvaluation, NativeHotkeyBinding } from './hotkeyAlternatives'

export function binding(key: string, modifiers: string[] = []): NativeHotkeyBinding {
  return { key, enabled: true, modifiers, isDoublePress: false, doublePressKey: null }
}

export const DOUBLE_OPTION: NativeHotkeyBinding = { key: '', enabled: true, modifiers: [], isDoublePress: true, doublePressKey: 'option' }
export const DOUBLE_COMMAND: NativeHotkeyBinding = { key: '', enabled: true, modifiers: [], isDoublePress: true, doublePressKey: 'command' }
export const OPTION_SPACE = binding('Space', ['option'])
export const CONTROL_OPTION_SPACE = binding('Space', ['control', 'option'])
export const CONTROL_OPTION_C = binding('C', ['control', 'option'])

export const SIRI_CONFLICT: HotkeyConflict = {
  hotkeyId: 'agent_task',
  kind: 'mac_shortcut',
  source: 'Siri',
  certainty: 'possible',
  message: 'Option Space may open Siri.',
}

export const MEDIA_CONFLICT: HotkeyConflict = {
  hotkeyId: 'agent_task',
  kind: 'media_key',
  source: 'Keyboard settings',
  certainty: 'possible',
  message: 'Function keys may act as media keys on this Mac.',
}

export function row(
  id: string,
  current: NativeHotkeyBinding,
  conflicts: HotkeyConflict[] = [],
  alternative: NativeHotkeyBinding | null = null,
): HotkeyRowEvaluation {
  return { id, binding: current, conflicts, alternative }
}

/** The five setup rows in the order setup shows them, with nothing clashing. */
export function cleanRows(): HotkeyRowEvaluation[] {
  return [
    row('assistant_session', DOUBLE_OPTION),
    row('agent_task', OPTION_SPACE),
    row('transcribe_audio', DOUBLE_COMMAND),
    row('conversation_toggle', binding('F8')),
    row('home_board_toggle', binding('B', ['control', 'option'])),
  ]
}

/** The same rows with the agent task hotkey clashing with Siri. */
export function clashingRows(alternative: NativeHotkeyBinding | null = CONTROL_OPTION_SPACE): HotkeyRowEvaluation[] {
  return cleanRows().map(item => (item.id === 'agent_task' ? { ...item, conflicts: [SIRI_CONFLICT], alternative } : item))
}

/** The rows after the agent task hotkey was changed to the given keys, with nothing clashing. */
export function rowsWithAgentTask(keys: NativeHotkeyBinding): HotkeyRowEvaluation[] {
  return cleanRows().map(item => (item.id === 'agent_task' ? { ...item, binding: keys } : item))
}

export function ok(payload: Record<string, unknown> | undefined): SetupBridgeActionResult {
  return { requestId: 'request-1', status: 'executed', message: 'ok', resultPayload: payload }
}
