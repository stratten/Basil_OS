import type { HotkeyBinding } from '../types'

export function modifierSymbol(modifier: string): string {
  switch (modifier.toLowerCase()) {
    case 'command':
    case 'cmd':
      return '⌘'
    case 'control':
    case 'ctrl':
      return '⌃'
    case 'option':
    case 'alt':
      return '⌥'
    case 'shift':
      return '⇧'
    default:
      return modifier
  }
}

export function keyDisplaySymbol(key: string): string {
  switch (key.toLowerCase()) {
    case 'space':
      return '␣'
    case 'return':
    case 'enter':
      return '⏎'
    case 'delete':
      return '⌫'
    case 'escape':
      return '⎋'
    case 'tab':
      return '⇥'
    default: {
      const functionKeyMatch = /^f(\d{1,2})$/i.exec(key)
      if (functionKeyMatch && Number(functionKeyMatch[1]) >= 1 && Number(functionKeyMatch[1]) <= 12) {
        return key.toUpperCase()
      }
      return key.toUpperCase()
    }
  }
}

/** One symbol per key cap to render for a binding, in display order. */
export function getBindingCapSymbols(binding: HotkeyBinding): string[] {
  if (binding.isDoublePress && binding.doublePressKey) {
    const symbol = modifierSymbol(binding.doublePressKey)
    return [symbol, symbol]
  }
  const symbols = binding.modifiers.map(modifierSymbol)
  if (binding.key) {
    symbols.push(keyDisplaySymbol(binding.key))
  }
  return symbols
}

export function HotkeyKeyCap({ symbol }: { symbol: string }) {
  return <span className="hotkey-key-cap">{symbol}</span>
}
