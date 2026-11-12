import {
  comfortTitle,
  downloadSizeLabel,
  groupItems,
  GROUP_LABELS,
  hasPreflightProblem,
  itemStatusLabel,
  permissionSentence,
  selectedItemIds,
  summaryForComfort,
} from './expressPlan'
import { HOTKEYS_ITEM_ID } from './expressNativeHotkeys'
import { THINKING_ITEM_ID, type ExpressItem, type ExpressPlan } from './expressTypes'
import { ExpressHotkeys } from './ExpressHotkeys'
import type { useSetupHotkeys } from '@/components/intro/useSetupHotkeys'

interface Props {
  plan: ExpressPlan
  /** The items shown. The container already removed any native item the app cannot act on. */
  items: ExpressItem[]
  deselected: ReadonlySet<string>
  isYolo: boolean
  isChecking: boolean
  isApplying: boolean
  applyError: string | null
  onToggle: (itemId: string) => void
  onCheckAgain: () => void
  onApply: () => void
  onChooseManual: () => void
  onBackToStart?: () => void
  /** The staged hotkey check, present only inside the Basil app window. It lets the person adjust hotkeys before Do it. */
  hotkeys?: ReturnType<typeof useSetupHotkeys>
}

function ItemRow({ item, ticked, onToggle }: { item: ExpressItem, ticked: boolean, onToggle: (itemId: string) => void }) {
  const locked = item.already_done || item.unavailable_reason !== null
  const size = downloadSizeLabel(item.download_size_gb)
  const status = itemStatusLabel(item)
  return (
    <li className="express-item">
      <label className="express-item-label">
        <input type="checkbox" checked={ticked} disabled={locked} onChange={() => onToggle(item.id)} />
        <span className="express-item-body">
          <strong>
            {item.title}
            {size && !item.already_done && <span className="express-item-size">{size}</span>}
            {item.id === THINKING_ITEM_ID && item.model_name && <span className="express-item-badge">Chosen for this Mac</span>}
          </strong>
          <span>{item.summary}</span>
          {item.model_name && <span>Model: {item.model_name}</span>}
          {item.caution && <span className="express-item-caution">{item.caution}</span>}
          {status && (
            <span className="express-item-status">
              {status}{item.unavailable_reason ? `. ${item.unavailable_reason}` : ''}
            </span>
          )}
        </span>
      </label>
    </li>
  )
}

/** The confirm screen for Self-setup and YOLO: a plain summary, the device and checks, a collapsed list of everything with a checkbox each, and one "Do it" button. */
export function ExpressReview({
  plan,
  items,
  deselected,
  isYolo,
  isChecking,
  isApplying,
  applyError,
  onToggle,
  onCheckAgain,
  onApply,
  onChooseManual,
  onBackToStart,
  hotkeys,
}: Props) {
  const ids = selectedItemIds(items, deselected)
  const selectable = items.filter(item => item.selected).length
  const permissions = permissionSentence(items, ids)

  return (
    <section className="phase-section express-review">
      <p className="eyebrow">{isYolo ? 'Everything' : `${comfortTitle(plan.comfort)} setup`}</p>
      <h2>Here is what I'll do on this Mac.</h2>
      <p className="express-review-summary">{summaryForComfort(plan.comfort, isYolo)}</p>
      <p className="express-review-device">This Mac: {plan.device.summary}.</p>

      <ul className="express-checks" aria-label="Checks before I start">
        {plan.preflight.map(check => (
          <li key={check.id} className={`express-check express-check--${check.ok ? 'ok' : 'problem'}`}>
            <span className="express-check-state">{check.ok ? 'OK' : 'Needs attention'}</span>
            <span>{check.message}</span>
          </li>
        ))}
      </ul>
      {hasPreflightProblem(plan) && (
        <button type="button" className="secondary-button express-check-again" disabled={isChecking} onClick={onCheckAgain}>
          {isChecking ? 'Checking…' : 'Check again'}
        </button>
      )}
      {plan.notes.map(note => <p key={note} className="express-note">{note}</p>)}

      {hotkeys && <ExpressHotkeys hotkeys={hotkeys} isIncluded={ids.includes(HOTKEYS_ITEM_ID)} />}

      <details className="express-items">
        <summary>What this turns on ({ids.length} of {selectable})</summary>
        {groupItems(items).map(entry => (
          <div key={entry.group} className="express-group">
            <h3>{GROUP_LABELS[entry.group]}</h3>
            <ul>
              {entry.items.map(item => (
                <ItemRow
                  key={item.id}
                  item={item}
                  ticked={item.already_done || (item.selected && !deselected.has(item.id))}
                  onToggle={onToggle}
                />
              ))}
            </ul>
          </div>
        ))}
      </details>

      {permissions && <p className="express-note">{permissions}</p>}
      {applyError && <p className="express-error" role="alert">{applyError}</p>}

      <div className="express-actions">
        <button type="button" className="primary-button express-do-it" disabled={isApplying} onClick={onApply}>
          {isApplying ? 'Working…' : 'Do it'}
        </button>
        <button type="button" className="secondary-button" disabled={isApplying} onClick={onChooseManual}>
          Set it up step by step instead
        </button>
        {onBackToStart && (
          <button type="button" className="secondary-button" disabled={isApplying} onClick={onBackToStart}>
            ← Back
          </button>
        )}
      </div>
    </section>
  )
}
