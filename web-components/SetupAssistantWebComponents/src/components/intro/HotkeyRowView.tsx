import { describeNativeBinding, type HotkeyConflict, type HotkeyRowEvaluation } from './hotkeyAlternatives'
import { type HotkeyRowPhase, type useSetupHotkeys } from './useSetupHotkeys'

type Hotkeys = ReturnType<typeof useSetupHotkeys>

function ConflictMessages({ conflicts }: { conflicts: readonly HotkeyConflict[] }) {
  return (
    <>
      {conflicts.map((conflict, index) => (
        <p key={`${index}-${conflict.kind}`}>
          {conflict.certainty === 'possible' ? 'Possible clash. ' : ''}
          {conflict.message}
        </p>
      ))}
    </>
  )
}

export interface HotkeyRowViewProps {
  id: string
  title: string
  purpose: string
  native: HotkeyRowEvaluation | undefined
  phase: HotkeyRowPhase
  hotkeys: Hotkeys
  /** True on the express confirm screen, where a choice is held until Do it instead of being saved at once. */
  staged?: boolean
}

/** One hotkey with its keys, what it is for, and, when it clashes, the ways to fix it: take the suggestion, record your own keys, or keep it. */
export function HotkeyRowView({ id, title, purpose, native, phase, hotkeys, staged = false }: HotkeyRowViewProps) {
  const keys = describeNativeBinding(native?.binding) ?? 'Off'
  const conflicts = native?.conflicts ?? []
  const alternativeKeys = describeNativeBinding(native?.alternative)
  const showsNotice =
    phase.kind === 'blocked' ||
    phase.kind === 'capturing' ||
    phase.kind === 'working' ||
    phase.kind === 'failed' ||
    ((phase.kind === 'idle' || phase.kind === 'kept') && conflicts.length > 0) ||
    (staged && phase.kind === 'changed')

  return (
    <div className="intro-hotkey-row">
      <dt>{title}</dt>
      <dd className="intro-hotkey-keys">
        <kbd>{keys}</kbd>
        {!showsNotice && (
          <button
            type="button"
            className="secondary-button"
            aria-label={`Change the keys for ${title}`}
            onClick={() => { void hotkeys.startCapture(id) }}
          >
            Change keys
          </button>
        )}
      </dd>
      <dd className="intro-hotkey-purpose">
        {purpose}
        {phase.kind === 'changed' && (
          <span className="intro-hotkey-status" role="status">
            {staged ? 'Will change when you press Do it.' : 'Saved.'}
            {conflicts.length > 0 ? ` ${staged ? "I'll keep" : 'I kept'} your choice even though it clashes.` : ''}
          </span>
        )}
        {phase.kind === 'kept' && (
          <span className="intro-hotkey-status" role="status">
            {staged
              ? `Keeping ${keys}. I won't change this one.`
              : `Keeping ${keys} for now. You can still choose different keys here, or change it later in Settings, Hotkeys.`}
          </span>
        )}
      </dd>
      {showsNotice && (
        <dd className="intro-hotkey-conflict">
          {phase.kind === 'capturing' ? (
            <>
              <p role="status">Press the new keys now. To use a double-press, tap a modifier key twice, such as Control.</p>
              <div className="intro-hotkey-actions">
                <button type="button" className="secondary-button" onClick={() => hotkeys.cancelCapture(id)}>Cancel</button>
              </div>
            </>
          ) : phase.kind === 'working' ? (
            <p role="status">Saving…</p>
          ) : phase.kind === 'changed' ? (
            <div className="intro-hotkey-actions">
              <button type="button" className="secondary-button" onClick={() => { void hotkeys.startCapture(id) }}>Choose different keys</button>
              <button type="button" className="secondary-button" onClick={() => hotkeys.resetChoice(id)}>Undo</button>
            </div>
          ) : phase.kind === 'blocked' ? (
            <>
              <p><strong>Those keys, <kbd>{describeNativeBinding(phase.binding) ?? 'that shortcut'}</kbd>, clash too.</strong></p>
              <ConflictMessages conflicts={phase.conflicts} />
              <div className="intro-hotkey-actions">
                <button type="button" className="primary-button" onClick={() => hotkeys.acceptBlocked(id)}>Use them anyway</button>
                <button type="button" className="secondary-button" onClick={() => { void hotkeys.startCapture(id) }}>Choose different keys</button>
                <button type="button" className="secondary-button" onClick={() => hotkeys.keepCurrent(id)}>Keep mine</button>
              </div>
            </>
          ) : conflicts.length === 0 ? (
            <>
              {phase.kind === 'failed' && <p role="alert">{phase.message}</p>}
              <div className="intro-hotkey-actions">
                <button type="button" className="secondary-button" onClick={() => { void hotkeys.startCapture(id) }}>Choose different keys</button>
              </div>
            </>
          ) : (
            <>
              <p><strong>This clashes with something on your Mac.</strong></p>
              <ConflictMessages conflicts={conflicts} />
              {alternativeKeys ? (
                <p>
                  {staged
                    ? <>Unless you choose otherwise, I'll switch it to <kbd>{alternativeKeys}</kbd> when you press Do it.</>
                    : <>I suggest <kbd>{alternativeKeys}</kbd> instead.</>}
                </p>
              ) : (
                <p>I couldn't find a free replacement, so you can choose your own keys or keep these.</p>
              )}
              {phase.kind === 'failed' && <p role="alert">{phase.message}</p>}
              <div className="intro-hotkey-actions">
                {alternativeKeys && (
                  <button
                    type="button"
                    className="primary-button"
                    aria-label={`Use ${alternativeKeys} for ${title}`}
                    onClick={() => hotkeys.applyAlternative(id)}
                  >
                    Use {alternativeKeys}
                  </button>
                )}
                <button type="button" className="secondary-button" onClick={() => { void hotkeys.startCapture(id) }}>Choose different keys</button>
                <button type="button" className="secondary-button" onClick={() => hotkeys.keepCurrent(id)}>Keep mine</button>
              </div>
            </>
          )}
        </dd>
      )}
    </div>
  )
}
