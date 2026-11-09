import { useEffect, useState } from 'react'

import { fetchHotkeyBindings } from '@/services/api'
import type { HotkeyBindingSnapshot } from '@/services/api'
import type { SetupSystemShortcutConflict } from '@/theme/themeBootstrap'

import { describeHotkeyBinding, SETUP_HOTKEY_ROWS } from './hotkeyDisplay'

type LoadState = 'loading' | 'ready' | 'unavailable'

export function IntroHotkeysReadOnly() {
  const [bindings, setBindings] = useState<Record<string, HotkeyBindingSnapshot>>({})
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const conflicts: SetupSystemShortcutConflict[] = window.basilSetupAssistantConfig?.systemShortcutConflicts ?? []

  useEffect(() => {
    let canceled = false
    fetchHotkeyBindings()
      .then(result => {
        if (canceled) return
        setBindings(result)
        setLoadState('ready')
      })
      .catch(() => {
        if (!canceled) setLoadState('unavailable')
      })
    return () => {
      canceled = true
    }
  }, [])

  return (
    <div className="intro-step-body">
      <h3>Your hotkeys</h3>
      <p className="intro-step-lede">
        These are how you reach Basil from any app. You can change any of them later in <em>Settings &gt; Hotkeys</em>.
      </p>

      {loadState === 'loading' && <p role="status">Checking your hotkeys…</p>}
      {loadState === 'unavailable' && (
        <p role="status">I couldn’t read your hotkeys right now. You can see and change them in <em>Settings &gt; Hotkeys</em>.</p>
      )}
      {loadState === 'ready' && (
        <dl className="intro-hotkey-list">
          {SETUP_HOTKEY_ROWS.map(row => {
            const keys = describeHotkeyBinding(bindings[row.id])
            return (
              <div key={row.id} className="intro-hotkey-row">
                <dt>{row.title}</dt>
                <dd className="intro-hotkey-keys"><kbd>{keys ?? 'Off'}</kbd></dd>
                <dd className="intro-hotkey-purpose">{row.purpose}</dd>
              </div>
            )
          })}
        </dl>
      )}

      {conflicts.length > 0 && (
        <div className="intro-hotkey-conflicts" role="alert">
          <strong>Heads up: macOS may use some of the same keys.</strong>
          {conflicts.map(conflict => (
            <p key={`${conflict.hotkeyId}-${conflict.source}`}>
              {conflict.certainty === 'exact' ? `Conflict with ${conflict.source}. ` : `Possible conflict with ${conflict.source}. `}
              {conflict.message}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
