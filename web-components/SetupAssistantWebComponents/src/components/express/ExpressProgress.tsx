import { ModelDownloadRows } from '@/components/layout/ModelDownloadRows'
import { startableRows } from '@/components/layout/starterDownloads'
import { useModelStarts } from '@/components/layout/useModelStarts'
import { SetupWorkingIndicator } from '@/components/motion/SetupWorkingIndicator'
import type { SetupAgentModelAccess } from '@/types'

import type { ExpressApplyResult, ExpressItemOutcome } from './expressTypes'
import { SetupReceiptSection } from './SetupReceiptSection'
import { useExpressRoute } from './useExpressRoute'

const OUTCOME_LABELS: Record<ExpressItemOutcome, string> = {
  started: 'Started',
  applied: 'Done',
  skipped: 'Skipped',
  failed: 'Needs attention',
}

interface Props {
  result: ExpressApplyResult
  onSelectModelAccess: (access: SetupAgentModelAccess) => void
  onFinished: () => void
  onChooseManual: () => void
}

/** After "Do it": what was done, live download progress, the receipt, and a Continue that waits for the thinking model. */
export function ExpressProgress({ result, onSelectModelAccess, onFinished, onChooseManual }: Props) {
  const route = useExpressRoute({ thinkingModelId: result.thinking_model_id, onSelectModelAccess })
  const { startingIds, error, startRows } = useModelStarts(route.refreshNow)
  // A started download is already shown as a progress row below, so the list only repeats the other outcomes.
  const notes = result.results.filter(item => item.outcome !== 'started')
  const receiptKey = `${route.state}|${route.rows.map(row => `${row.id}:${row.state}`).join(',')}`

  return (
    <section className="phase-section express-progress">
      <p className="eyebrow">Setting up</p>
      <h2>{route.state === 'ready' ? 'This Mac is ready.' : 'Getting this Mac ready.'}</h2>

      {notes.length > 0 && (
        <ul className="express-results" aria-live="polite">
          {notes.map(item => (
            <li key={item.id} className={`express-result express-result--${item.outcome}`} role={item.outcome === 'failed' ? 'alert' : undefined}>
              <span className="express-result-state">{OUTCOME_LABELS[item.outcome]}</span>
              <span>{item.message}</span>
            </li>
          ))}
        </ul>
      )}

      {route.rows.length > 0 ? (
        <ModelDownloadRows
          rows={route.rows}
          startingIds={startingIds}
          error={error}
          onStart={(row, method) => { void startRows([row], method) }}
          onStartAll={(method) => { void startRows(startableRows(route.rows), method) }}
        />
      ) : route.state === 'waiting' ? (
        <SetupWorkingIndicator className="express-working" label="Checking the downloads." />
      ) : null}

      {route.state === 'waiting' && (
        <p className="express-note" role="status">I'll let you continue as soon as the thinking model has finished downloading. You can leave this open while it works.</p>
      )}
      {route.state === 'selecting' && <p className="express-note" role="status">Confirming the local model as how I think…</p>}
      {route.state === 'ready' && <p className="express-note" role="status">The thinking model is ready, and I'll use it.</p>}
      {route.state === 'needs_manual' && route.message && <p className="express-error" role="alert">{route.message}</p>}

      <SetupReceiptSection refreshKey={receiptKey} />

      <p className="express-note">
        To bring in your history, a profile, or exports from another app, open Settings, then Personalization, then Personal Context, whenever you like. Captures can be added there one memory at a time.
      </p>

      <div className="express-actions">
        <button type="button" className="primary-button express-continue" disabled={route.state !== 'ready'} onClick={onFinished}>
          Continue to our conversation
        </button>
        <button type="button" className="secondary-button" onClick={onChooseManual}>
          Choose how I think instead
        </button>
      </div>
    </section>
  )
}
