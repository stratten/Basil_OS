import { SETUP_HOTKEY_ROWS } from './hotkeyDisplay'
import { HotkeyRowView } from './HotkeyRowView'
import { IntroHotkeysReadOnly } from './IntroHotkeysReadOnly'
import { useSetupHotkeys, type HotkeyRowPhase } from './useSetupHotkeys'

const IDLE_PHASE: HotkeyRowPhase = { kind: 'idle' }

export function IntroHotkeysStep() {
  const hotkeys = useSetupHotkeys()
  if (hotkeys.status === 'unavailable') return <IntroHotkeysReadOnly />

  const nativeById = new Map(hotkeys.rows.map(row => [row.id, row]))
  const allClear = hotkeys.rows.every(row => row.conflicts.length === 0)

  return (
    <div className="intro-step-body">
      <h3>Your hotkeys</h3>
      <p className="intro-step-lede">
        These are how you reach Basil from any app. If one clashes with something on this Mac, I'll suggest a free replacement. You can change any of them here, or later in <em>Settings &gt; Hotkeys</em>.
      </p>

      {hotkeys.status === 'loading' && <p role="status">Checking your hotkeys…</p>}
      {hotkeys.status === 'ready' && (
        <>
          {allClear && <p className="intro-hotkey-clear" role="status">Nothing here clashes with anything on this Mac.</p>}
          <dl className="intro-hotkey-list">
            {SETUP_HOTKEY_ROWS.map(row => (
              <HotkeyRowView
                key={row.id}
                id={row.id}
                title={row.title}
                purpose={row.purpose}
                native={nativeById.get(row.id)}
                phase={hotkeys.phases[row.id] ?? IDLE_PHASE}
                hotkeys={hotkeys}
              />
            ))}
          </dl>
        </>
      )}
    </div>
  )
}
