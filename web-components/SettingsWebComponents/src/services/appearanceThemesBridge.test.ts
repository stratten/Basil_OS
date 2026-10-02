// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  deleteAppearanceTheme,
  notifyAppearanceThemesReady,
  onAppearanceThemesEvent,
  saveAppearanceTheme,
} from './appearanceThemesBridge'
import type { CustomAppearanceThemeInput } from '../types'

let postMessage: ReturnType<typeof vi.fn>

const themeInput: CustomAppearanceThemeInput = {
  name: 'Harbor',
  backgroundColorRed: 0.1,
  backgroundColorGreen: 0.2,
  backgroundColorBlue: 0.3,
  primaryColorRed: 0.4,
  primaryColorGreen: 0.5,
  primaryColorBlue: 0.6,
  secondaryColorRed: 0.7,
  secondaryColorGreen: 0.8,
  secondaryColorBlue: 0.9,
  textColorRed: 1,
  textColorGreen: 0.95,
  textColorBlue: 0.9,
  surfaceFinish: 'metal',
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilAppearanceThemesBridge: { postMessage } } }
})

describe('appearanceThemesBridge', () => {
  it('posts reactReady with protocolVersion 1', () => {
    notifyAppearanceThemesReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('posts saveTheme and deleteTheme with unique request ids', () => {
    const saveId = saveAppearanceTheme(themeInput)
    const deleteId = deleteAppearanceTheme('custom-0123456789abcdef0123456789abcdef')
    expect(saveId).not.toBe(deleteId)
    expect(postMessage).toHaveBeenCalledWith({ type: 'saveTheme', requestId: saveId, theme: themeInput })
    expect(postMessage).toHaveBeenCalledWith({
      type: 'deleteTheme',
      requestId: deleteId,
      themeId: 'custom-0123456789abcdef0123456789abcdef',
    })
  })

  it('replays events queued before subscription and stops delivering after unsubscribe', () => {
    window.basilAppearanceThemes!.onEvent({ type: 'init', protocolVersion: 1, themes: [] })
    const handler = vi.fn()
    const unsubscribe = onAppearanceThemesEvent(handler)
    expect(handler).toHaveBeenCalledWith({ type: 'init', protocolVersion: 1, themes: [] })

    window.basilAppearanceThemes!.onEvent({ type: 'loadError', message: 'Failed to load saved themes.' })
    expect(handler).toHaveBeenCalledWith({ type: 'loadError', message: 'Failed to load saved themes.' })

    unsubscribe()
    window.basilAppearanceThemes!.onEvent({ type: 'snapshot', themes: [] })
    expect(handler).toHaveBeenCalledTimes(2)
  })
})
