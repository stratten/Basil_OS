// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { getBindingCapSymbols, keyDisplaySymbol, modifierSymbol } from './HotkeyKeyCap'

describe('modifierSymbol', () => {
  it('maps every known modifier name and alias', () => {
    expect(modifierSymbol('command')).toBe('⌘')
    expect(modifierSymbol('cmd')).toBe('⌘')
    expect(modifierSymbol('control')).toBe('⌃')
    expect(modifierSymbol('ctrl')).toBe('⌃')
    expect(modifierSymbol('option')).toBe('⌥')
    expect(modifierSymbol('alt')).toBe('⌥')
    expect(modifierSymbol('shift')).toBe('⇧')
  })

  it('returns the raw string for an unrecognized modifier', () => {
    expect(modifierSymbol('fn')).toBe('fn')
  })
})

describe('keyDisplaySymbol', () => {
  it('maps every known special key', () => {
    expect(keyDisplaySymbol('Space')).toBe('␣')
    expect(keyDisplaySymbol('Return')).toBe('⏎')
    expect(keyDisplaySymbol('Enter')).toBe('⏎')
    expect(keyDisplaySymbol('Delete')).toBe('⌫')
    expect(keyDisplaySymbol('Escape')).toBe('⎋')
    expect(keyDisplaySymbol('Tab')).toBe('⇥')
  })

  it('uppercases function keys F1 through F12', () => {
    expect(keyDisplaySymbol('f8')).toBe('F8')
    expect(keyDisplaySymbol('F12')).toBe('F12')
  })

  it('uppercases any other single character or word', () => {
    expect(keyDisplaySymbol('a')).toBe('A')
  })
})

describe('getBindingCapSymbols', () => {
  it('renders two identical modifier symbols for a double-press binding', () => {
    const binding = { key: '', modifiers: [], enabled: true, isDoublePress: true, doublePressKey: 'option' }
    expect(getBindingCapSymbols(binding)).toEqual(['⌥', '⌥'])
  })

  it('renders modifiers followed by the key for a traditional binding', () => {
    const binding = { key: 'Space', modifiers: ['option'], enabled: true, isDoublePress: false, doublePressKey: null }
    expect(getBindingCapSymbols(binding)).toEqual(['⌥', '␣'])
  })

  it('renders no key cap for an empty, non-double-press binding', () => {
    const binding = { key: '', modifiers: [], enabled: false, isDoublePress: false, doublePressKey: null }
    expect(getBindingCapSymbols(binding)).toEqual([])
  })
})
