import { describe, expect, it } from 'vitest'

import type { SetupActionExecutionItem } from '@/types'

import { buildAppearanceChangeSummary } from './appearanceChangeSummary'

function fixture(
  result_payload: Record<string, unknown>,
  kind = 'update_settings',
): SetupActionExecutionItem {
  return {
    id: 'action-1',
    kind,
    status: 'applied',
    message: 'Updated setting.',
    result_payload,
  }
}

describe('buildAppearanceChangeSummary', () => {
  it('returns null for non-appearance actions and empty changes', () => {
    expect(buildAppearanceChangeSummary(fixture({}, 'refresh_connection_tools'))).toBeNull()
    expect(buildAppearanceChangeSummary(fixture({ appearance_settings: {} }))).toBeNull()
    expect(buildAppearanceChangeSummary(fixture({ ui_changes: [], appearance_settings: {} }))).toBeNull()
  })

  it('builds an old and new swatch from a changed color triplet', () => {
    const summary = buildAppearanceChangeSummary(fixture({
      ui_changes: [
        { path: 'ui.background_color_red', old_value: 1, new_value: 0.1 },
        { path: 'ui.background_color_green', old_value: 1, new_value: 0.1 },
        { path: 'ui.background_color_blue', old_value: 1, new_value: 0.1 },
      ],
      appearance_settings: {
        background_color_red: 0.1,
        background_color_green: 0.1,
        background_color_blue: 0.1,
      },
    }))

    expect(summary?.rows).toEqual([
      { kind: 'color', label: 'Background', oldColor: 'rgb(255, 255, 255)', newColor: 'rgb(26, 26, 26)' },
    ])
    expect(summary?.contrastWarning).toBeNull()
  })

  it('uses current sibling channels when only one color channel changed', () => {
    const summary = buildAppearanceChangeSummary(fixture({
      ui_changes: [{ path: 'ui.text_color_red', old_value: 0, new_value: 1 }],
      appearance_settings: { text_color_red: 1, text_color_green: 0, text_color_blue: 0 },
    }))

    expect(summary?.rows).toEqual([
      { kind: 'color', label: 'Text', oldColor: 'rgb(0, 0, 0)', newColor: 'rgb(255, 0, 0)' },
    ])
  })

  it('renders font changes without creating a color swatch', () => {
    const summary = buildAppearanceChangeSummary(fixture({
      ui_changes: [{ path: 'ui.preferred_font', old_value: 'Arial', new_value: 'Menlo' }],
      appearance_settings: { preferred_font: 'Menlo' },
    }))

    expect(summary?.rows).toEqual([
      { kind: 'font', label: 'Font', oldFont: 'Arial', newFont: 'Menlo' },
    ])
  })

  it('carries a valid contrast warning through', () => {
    const summary = buildAppearanceChangeSummary(fixture({
      ui_changes: [{ path: 'ui.text_color_red', old_value: 0, new_value: 1 }],
      appearance_settings: { text_color_red: 1, text_color_green: 1, text_color_blue: 1 },
      contrast_warning: { ratio: 1.8, required_ratio: 4.5 },
    }))

    expect(summary?.contrastWarning).toEqual({ ratio: 1.8, requiredRatio: 4.5 })
  })

  it('ignores malformed changes and invalid color channels without throwing', () => {
    const result = fixture({
      ui_changes: [null, 'not-an-object', { path: 'ui.text_color_red', old_value: 2, new_value: 0.5 }],
      appearance_settings: { text_color_red: 0.5, text_color_green: 0.5, text_color_blue: 0.5 },
    })

    expect(() => buildAppearanceChangeSummary(result)).not.toThrow()
    expect(buildAppearanceChangeSummary(result)).toBeNull()
  })
})
