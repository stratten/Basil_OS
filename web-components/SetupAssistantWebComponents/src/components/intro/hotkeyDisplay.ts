import type { HotkeyBindingSnapshot } from '@/services/api'

const MODIFIER_SYMBOLS: Record<string, string> = {
  command: '⌘',
  cmd: '⌘',
  option: '⌥',
  alt: '⌥',
  control: '⌃',
  ctrl: '⌃',
  shift: '⇧',
}

// The rows the Hotkeys settings page shows, in the same order, with the plain-language job of each.
export const SETUP_HOTKEY_ROWS: ReadonlyArray<{ id: string; title: string; purpose: string }> = [
  { id: 'assistant_session', title: 'Dill, quick assist', purpose: 'Ask for help drafting, summarizing or finding words in the moment.' },
  { id: 'agent_task', title: 'Paprika, agent tasks', purpose: 'Hand Basil a task to work through.' },
  { id: 'transcribe_audio', title: 'Transcribe audio', purpose: 'Dictate text wherever you are typing.' },
  { id: 'conversation_toggle', title: 'Toggle conversation', purpose: 'Start or stop recording a conversation.' },
  { id: 'home_board_toggle', title: 'Open Basil Home', purpose: 'Show or hide the Basil Home board.' },
]

/** The keys of a binding as a short, readable string, for example "⌥␣" or "⌘⌘ (press twice)". Returns null when the binding is off or empty. */
export function describeHotkeyBinding(binding: HotkeyBindingSnapshot | undefined): string | null {
  if (!binding || !binding.enabled) return null
  if (binding.is_double_press && binding.double_press_key) {
    const symbol = MODIFIER_SYMBOLS[binding.double_press_key.toLowerCase()] ?? binding.double_press_key
    return `${symbol}${symbol} (press twice)`
  }
  if (!binding.key) return null
  const modifiers = binding.modifiers.map(modifier => MODIFIER_SYMBOLS[modifier.toLowerCase()] ?? modifier).join('')
  const key = binding.key.toLowerCase() === 'space' ? '␣' : binding.key.toUpperCase()
  return `${modifiers}${key}`
}
