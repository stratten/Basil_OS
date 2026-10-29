import { createContext, useContext } from 'react'
import type { HotkeyId, HotkeyInfo, HotkeyMap } from './types'

/** What the guide shows until the app reports the user's saved hotkeys, and for any hotkey the app does not report. These mirror the app's shipped defaults. */
export const DEFAULT_HOTKEYS: Record<HotkeyId, HotkeyInfo> = {
  transcription: { display: '⌘⌘', enabled: true, isDoublePress: true, doublePressKey: 'command' },
  assistantSession: { display: '⌥⌥', enabled: true, isDoublePress: true, doublePressKey: 'option' },
  agentTask: { display: '⌥␣', enabled: true, isDoublePress: false },
  conversation: { display: 'F8', enabled: true, isDoublePress: false },
}

const MODIFIER_NAMES: Record<string, string> = {
  command: 'Command',
  cmd: 'Command',
  option: 'Option',
  alt: 'Option',
  control: 'Control',
  ctrl: 'Control',
  shift: 'Shift',
}

export const HotkeysContext = createContext<HotkeyMap>({})

export function resolveHotkey(map: HotkeyMap, id: HotkeyId): HotkeyInfo {
  return map[id] ?? DEFAULT_HOTKEYS[id]
}

export function useHotkey(id: HotkeyId): HotkeyInfo {
  return resolveHotkey(useContext(HotkeysContext), id)
}

/** The keycaps as written in the guide. The app's Space glyph becomes the word, which reads better in running text. */
export function hotkeyKeys(info: HotkeyInfo): string {
  return info.display.replace('␣', 'Space')
}

/** The keys with the gesture spelled out when it is a double-tap, such as "⌥⌥ (double-tap Option)". */
export function hotkeyPhrase(info: HotkeyInfo): string {
  const keys = hotkeyKeys(info)
  if (!info.isDoublePress) return keys
  const modifier = info.doublePressKey ? MODIFIER_NAMES[info.doublePressKey.toLowerCase()] ?? info.doublePressKey : undefined
  return modifier ? `${keys} (double-tap ${modifier})` : keys
}

/** Inline keycaps for a hotkey, followed by a note when the user has turned that hotkey off. */
export function Hotkey({ id, spellOutGesture = false }: { id: HotkeyId; spellOutGesture?: boolean }) {
  const info = useHotkey(id)
  return (
    <>
      <kbd className="pug-hotkey">{spellOutGesture ? hotkeyPhrase(info) : hotkeyKeys(info)}</kbd>
      {!info.enabled && <span className="pug-hotkey-off"> (currently turned off in Settings → Hotkeys)</span>}
    </>
  )
}
