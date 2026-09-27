import type { HotkeyRowSnapshot } from '../types'

export const HOTKEY_FIXTURE_ROWS: HotkeyRowSnapshot[] = [
  {
    id: 'transcribe_audio',
    title: 'Transcribe Audio',
    subtitle: null,
    binding: { key: '', modifiers: [], enabled: true, isDoublePress: true, doublePressKey: 'command' },
  },
  {
    id: 'conversation_toggle',
    title: 'Toggle Conversation',
    subtitle: null,
    binding: { key: 'F8', modifiers: [], enabled: true, isDoublePress: false, doublePressKey: null },
  },
  {
    id: 'assistant_session',
    title: 'Dill',
    subtitle: 'Writing partner',
    binding: { key: '', modifiers: [], enabled: true, isDoublePress: true, doublePressKey: 'option' },
  },
  {
    id: 'agent_task',
    title: 'Paprika',
    subtitle: 'Side-quest helper',
    binding: { key: 'Space', modifiers: ['option'], enabled: true, isDoublePress: false, doublePressKey: null },
  },
]

export const HOTKEY_FIXTURE_ENABLE_MONITORING_AT_STARTUP = true
