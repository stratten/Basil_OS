import { useCallback, useEffect, useState } from 'react'

import './context-import-panel.css'
import { BasilModalDialog } from './BasilModalDialog'
import type {
  ContextImportBatch,
  ContextImportCategory,
  ContextImportClient,
  ContextImportCommitResult,
  ContextImportPreview,
} from './contextImportClient'
import { ImportJobProgress } from './ImportJobProgress'
import { ImportSourceInput } from './ImportSourceInput'
import { useContextImportJob } from './useContextImportJob'

const CATEGORY_ORDER: ContextImportCategory[] = ['dated', 'undated', 'stable_fact']

/** The working and review dialogs end only through their own buttons, so Escape and a backdrop click do nothing. */
const keepOpen = () => {}

type Stage = 'input' | 'review' | 'committing' | 'done'

interface Props {
  client: ContextImportClient
  /** One plain sentence saying where the text goes, shown above the text box. */
  routeNotice: string
  /** Past imports and their Undo buttons belong in Settings. */
  showPastImports?: boolean
  /** Called once an approved import has been written. */
  onImported?: (result: ContextImportCommitResult, preview: ContextImportPreview) => void
}

function formatDay(iso: string | null): string {
  if (!iso) return ''
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
}

function categoryHeading(category: ContextImportCategory, count: number, preview: ContextImportPreview): string {
  if (category === 'dated') {
    const range = preview.earliest && preview.latest ? `, from ${formatDay(preview.earliest)} to ${formatDay(preview.latest)}` : ''
    return `${count} dated ${count === 1 ? 'entry' : 'entries'}${range}`
  }
  if (category === 'undated') return `${count} undated ${count === 1 ? 'note' : 'notes'}`
  return `${count} ${count === 1 ? 'fact' : 'facts'} about you`
}

const CATEGORY_EXPLANATION: Record<ContextImportCategory, string> = {
  dated: 'Added to your searchable history on their own dates, so Basil can answer questions about when things happened.',
  undated: 'Added to your searchable history with today as the date. Basil finds them by searching their words.',
  stable_fact: 'Proposed one at a time under Pending Memory Proposals. None becomes always-known until you approve it there.',
}

export function ContextImportPanel({ client, routeNotice, showPastImports = false, onImported }: Props) {
  const [stage, setStage] = useState<Stage>('input')
  const [text, setText] = useState('')
  const [filename, setFilename] = useState('')
  const [preview, setPreview] = useState<ContextImportPreview | null>(null)
  const [chosen, setChosen] = useState<Set<ContextImportCategory>>(new Set())
  const [result, setResult] = useState<ContextImportCommitResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [batches, setBatches] = useState<ContextImportBatch[]>([])
  const [batchesError, setBatchesError] = useState<string | null>(null)
  const [confirmingUndo, setConfirmingUndo] = useState<string | null>(null)
  const [undoingId, setUndoingId] = useState<string | null>(null)
  const { view, start, cancel, reset: resetJob } = useContextImportJob<ContextImportPreview>(client)

  const working = view.phase === 'starting' || view.phase === 'running'
  const busy = working || stage === 'committing'

  const refreshBatches = useCallback(async () => {
    if (!showPastImports) return
    try {
      setBatches(await client.listBatches())
      setBatchesError(null)
    } catch (error) {
      setBatchesError(error instanceof Error ? error.message : 'Past imports could not be loaded.')
    }
  }, [client, showPastImports])

  useEffect(() => { void refreshBatches() }, [refreshBatches])

  useEffect(() => {
    if (view.phase !== 'done' || !view.result) return
    const next = view.result
    setPreview(next)
    setChosen(new Set(CATEGORY_ORDER.filter(category => next.counts[category] > 0)))
    setStage('review')
    resetJob()
  }, [view, resetJob])

  const begin = () => {
    if (!text.trim() || working) return
    setErrorMessage(null)
    void start(() => client.startRecordsJob(text, filename, filename))
  }

  const approve = async () => {
    if (!preview || busy || chosen.size === 0) return
    setErrorMessage(null)
    setStage('committing')
    try {
      const committed = await client.commit(preview.preview_id, CATEGORY_ORDER.filter(category => chosen.has(category)))
      setResult(committed)
      setStage('done')
      onImported?.(committed, preview)
      void refreshBatches()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'The import could not be saved.')
      setStage('review')
    }
  }

  const reset = () => {
    resetJob()
    setText('')
    setFilename('')
    setPreview(null)
    setResult(null)
    setErrorMessage(null)
    setStage('input')
  }

  const undo = async (batchId: string) => {
    setUndoingId(batchId)
    setBatchesError(null)
    try {
      await client.undo(batchId)
      setConfirmingUndo(null)
      await refreshBatches()
    } catch (error) {
      setBatchesError(error instanceof Error ? error.message : 'The import could not be undone.')
    } finally {
      setUndoingId(null)
    }
  }

  const toggleCategory = (category: ContextImportCategory) => {
    setChosen(current => {
      const next = new Set(current)
      if (next.has(category)) next.delete(category)
      else next.add(category)
      return next
    })
  }

  const jobProblem = view.phase === 'failed' ? view.error : null
  const canceledNote = view.phase === 'canceled' ? view.message : null
  // While the review dialog is open it shows its own save error, so the page behind it shows only a failed read.
  const pageError = (stage === 'review' || stage === 'committing' ? null : errorMessage) ?? jobProblem

  return (
    <div className="context-import" data-testid="context-import">
      <h3 className="context-import-title">Import personal context</h3>
      <p className="context-import-lede">Drop your personal info here if you have it available.</p>
      <p className="context-import-hint">Paste text, or choose a file. A model reads it and turns it into separate memories, and nothing is saved until you approve it below.</p>

      {stage === 'input' && (
        <>
          <ImportSourceInput
            inputId="context-import-text"
            placeholder={'For example:\n- I live in Boston and work in biotech.\n- 2023-06-01: Ran my first half marathon.'}
            routeNotice={routeNotice}
            startLabel="Review import"
            workingLabel="Reading..."
            working={working}
            text={text}
            filename={filename}
            onChange={(nextText, nextFilename) => { setText(nextText); setFilename(nextFilename) }}
            onStart={begin}
          />
          {canceledNote && <p className="context-import-hint" role="status">{canceledNote}</p>}
        </>
      )}

      {working && (
        <BasilModalDialog title="Reading your text" onClose={keepOpen} dismissible={false} testId="context-import-working">
          <ImportJobProgress
            kind="records"
            phase={view.phase === 'starting' ? 'starting' : 'running'}
            message={view.message}
            done={view.done}
            total={view.total}
            stage={view.stage}
            tokensWritten={view.tokensWritten}
            thinking={view.thinking}
            onCancel={() => { void cancel() }}
          />
        </BasilModalDialog>
      )}

      {(stage === 'review' || stage === 'committing') && preview && (
        <BasilModalDialog title="Review what I found" onClose={keepOpen} dismissible={false} size="wide" testId="context-import-review-modal">
        <div className="context-import-review-panel" data-testid="context-import-review">
          <p className="context-import-summary">I found {preview.total} {preview.total === 1 ? 'entry' : 'entries'} in {preview.label || 'your text'}. Choose what to keep, then approve.</p>
          {preview.warnings.length > 0 && (
            <ul className="context-import-warnings" role="status">
              {preview.warnings.map(warning => <li key={warning}>{warning}</li>)}
            </ul>
          )}
          {CATEGORY_ORDER.filter(category => preview.counts[category] > 0).map(category => (
            <div key={category} className="context-import-category">
              <label className="context-import-category-label">
                <input type="checkbox" checked={chosen.has(category)} disabled={busy} onChange={() => toggleCategory(category)} />
                <span>{categoryHeading(category, preview.counts[category], preview)}</span>
              </label>
              <p className="context-import-hint">{CATEGORY_EXPLANATION[category]}</p>
              <ul className="context-import-samples">
                {preview.samples[category].map((sample, index) => (
                  <li key={`${index}-${sample.title}`}>{sample.occurred_at ? `${formatDay(sample.occurred_at)}: ` : ''}{sample.text}</li>
                ))}
              </ul>
            </div>
          ))}
          <div className="context-import-actions">
            <button type="button" className="secondary-button" disabled={busy} onClick={reset}>Cancel</button>
            <button type="button" className="primary-button context-import-approve" disabled={busy || chosen.size === 0} onClick={() => { void approve() }}>
              {stage === 'committing' ? 'Saving...' : 'Approve import'}
            </button>
          </div>
          {errorMessage && <p className="context-import-error" role="alert">{errorMessage}</p>}
        </div>
        </BasilModalDialog>
      )}

      {stage === 'done' && result && (
        <div className="context-import-done" role="status" data-testid="context-import-done">
          <p className="context-import-summary">
            {result.entries_added > 0 ? `Added ${result.entries_added} ${result.entries_added === 1 ? 'entry' : 'entries'} to your searchable history.` : 'Nothing new was added to your searchable history.'}
            {result.entries_already_present > 0 ? ` ${result.entries_already_present} already existed from an earlier import.` : ''}
            {result.proposals_queued > 0 ? ` ${result.proposals_queued} ${result.proposals_queued === 1 ? 'fact is' : 'facts are'} waiting for your approval under Settings, Personalization, Personal Context.` : ''}
            {result.proposals_already_known > 0 ? ` ${result.proposals_already_known} ${result.proposals_already_known === 1 ? 'fact was' : 'facts were'} already known.` : ''}
          </p>
          {result.memory_file_warning && <p className="context-import-warnings" role="alert">{result.memory_file_warning}</p>}
          <button type="button" className="secondary-button" onClick={reset}>Import something else</button>
        </div>
      )}

      {pageError && <p className="context-import-error" role="alert">{pageError}</p>}

      {showPastImports && (
        <div className="context-import-past">
          <h4 className="context-import-subtitle">Past imports</h4>
          {batchesError && <p className="context-import-error" role="alert">{batchesError}</p>}
          {batches.length === 0 && !batchesError && <p className="context-import-hint">Nothing has been imported yet.</p>}
          <ul className="context-import-batches">
            {batches.map(batch => (
              <li key={batch.batch_id} className="context-import-batch">
                <span className="context-import-batch-name">{batch.label || 'Imported text'}, {batch.entry_count} {batch.entry_count === 1 ? 'entry' : 'entries'}, {formatDay(batch.imported_at)}</span>
                {confirmingUndo === batch.batch_id ? (
                  <span className="context-import-batch-confirm">
                    <button type="button" className="secondary-button" disabled={undoingId === batch.batch_id} onClick={() => setConfirmingUndo(null)}>Keep</button>
                    <button type="button" className="primary-button" disabled={undoingId === batch.batch_id} onClick={() => { void undo(batch.batch_id) }}>
                      {undoingId === batch.batch_id ? 'Removing...' : `Remove ${batch.entry_count}`}
                    </button>
                  </span>
                ) : (
                  <button type="button" className="secondary-button" onClick={() => setConfirmingUndo(batch.batch_id)}>Undo import</button>
                )}
              </li>
            ))}
          </ul>
          <p className="context-import-hint">Undoing an import removes its entries from your history. Facts you already approved into your memory files stay until you edit them there.</p>
        </div>
      )}
    </div>
  )
}
