import { useEffect, useRef, useState } from 'react'
import TokenizedSelect from '@shared/TokenizedSelect'
import { plainMarkdownText } from '@shared/plainMarkdownText'
import { useCopyFeedback } from '@shared/useCopyFeedback'
import { RecipientChipList, RecipientChipsInput } from '../components/RecipientChips'
import { WritingSampleMarkdown } from '../components/WritingSampleMarkdown'
import {
  analyzeWritingStyle,
  copyWritingSampleToClipboard,
  notifyWritingExamplesSettingsReady,
  onWritingExamplesEvent,
  requestAddWritingSample,
  requestDeleteAllWritingSamples,
  requestDeleteWritingSample,
  requestUpdateWritingSample,
  setWritingExamplesContextFilter,
} from '../services/writingExamplesBridge'
import type { WritingExampleSample, WritingExampleStyleProfile, WritingExamplesContextFilter } from '../types'

interface PendingRequest {
  id: string
  kind: 'delete' | 'deleteAll' | 'analyze' | 'update' | 'add'
  markContexts?: string[]
  clearContext?: string
}

interface EditDraft {
  content: string
  contextType: string
  recipient: string
}

interface StatusMessage {
  text: string
  isError: boolean
}

const FILTER_OPTIONS: { value: WritingExamplesContextFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'email_reply', label: 'Email Reply' },
  { value: 'email_compose', label: 'Email Compose' },
  { value: 'social_media', label: 'Social Media' },
  { value: 'document', label: 'Document' },
]

const CONCRETE_CONTEXT_OPTIONS = FILTER_OPTIONS.filter((option) => option.value !== 'all')

const EMPTY_EDIT_DRAFT: EditDraft = { content: '', contextType: 'email_reply', recipient: '' }

function contextDisplayName(contextType: string): string {
  return FILTER_OPTIONS.find((option) => option.value === contextType)?.label ?? contextType.replace(/_/g, ' ')
}

function editContextOptions(currentContextType: string): { value: string; label: string }[] {
  if (CONCRETE_CONTEXT_OPTIONS.some((option) => option.value === currentContextType)) return CONCRETE_CONTEXT_OPTIONS
  return [...CONCRETE_CONTEXT_OPTIONS, { value: currentContextType, label: contextDisplayName(currentContextType) }]
}

function formatCreatedAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function formalityDescription(level: number): string {
  if (level < 0.35) return 'Casual'
  if (level < 0.65) return 'Professional'
  return 'Formal'
}

function confidenceDescription(confidence: number): string {
  if (confidence < 0.4) return 'Low confidence - need more samples'
  if (confidence < 0.7) return 'Moderate confidence'
  if (confidence < 0.9) return 'High confidence'
  return 'Very high confidence'
}

export function WritingExamplesSettingsApp() {
  const [hasLoaded, setHasLoaded] = useState(false)
  const [activeFilter, setActiveFilter] = useState<WritingExamplesContextFilter>('all')
  const [samples, setSamples] = useState<WritingExampleSample[]>([])
  const [styleProfile, setStyleProfile] = useState<WritingExampleStyleProfile | null>(null)
  const [isLoadingSamples, setIsLoadingSamples] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<StatusMessage | null>(null)
  const [pending, setPending] = useState<PendingRequest | null>(null)
  const [expandedSampleId, setExpandedSampleId] = useState<string | null>(null)
  const { copiedKey: copiedSampleId, flash: flashCopiedSample } = useCopyFeedback<string>()
  const [editingSampleId, setEditingSampleId] = useState<string | null>(null)
  const [editingDraft, setEditingDraft] = useState<EditDraft>(EMPTY_EDIT_DRAFT)
  const [changedContexts, setChangedContexts] = useState<ReadonlySet<string>>(() => new Set())
  const [isAddFormOpen, setIsAddFormOpen] = useState(false)
  const [addDraft, setAddDraft] = useState({
    contextType: 'email_reply' as WritingExamplesContextFilter,
    content: '',
    recipient: '',
  })
  const pendingRef = useRef<PendingRequest | null>(null)
  pendingRef.current = pending

  useEffect(() => {
    const unsubscribe = onWritingExamplesEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setHasLoaded(true)
        setActiveFilter(event.activeFilter)
        setSamples(event.samples)
        setStyleProfile(event.styleProfile)
        setIsLoadingSamples(event.isLoadingSamples)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRef.current?.id) {
        const completedRequest = pendingRef.current
        pendingRef.current = null
        setPending(null)
        const markedContexts = completedRequest?.markContexts ?? []
        if (event.status === 'success' && markedContexts.length > 0) {
          setChangedContexts((current) => new Set([...current, ...markedContexts]))
        }
        const clearedContext = completedRequest?.clearContext
        if (event.status === 'success' && clearedContext) {
          setChangedContexts((current) => {
            const next = new Set(current)
            next.delete(clearedContext)
            return next
          })
        }
        if (event.status === 'success' && completedRequest?.kind === 'update') {
          setEditingSampleId(null)
          setEditingDraft(EMPTY_EDIT_DRAFT)
        }
        if (event.status === 'success' && completedRequest?.kind === 'add') {
          setIsAddFormOpen(false)
          setAddDraft({ contextType: 'email_reply', content: '', recipient: '' })
        }
        if (event.status === 'canceled') {
          setStatusMessage(null)
        } else {
          setStatusMessage(
            event.message
              ? { text: event.message, isError: event.status === 'error' }
              : event.status === 'error' ? { text: 'Something went wrong.', isError: true } : null
          )
        }
      }
    })
    notifyWritingExamplesSettingsReady()
    return unsubscribe
  }, [])

  function handleFilterChange(filter: WritingExamplesContextFilter) {
    if (filter === activeFilter) return
    setExpandedSampleId(null)
    setEditingSampleId(null)
    setEditingDraft(EMPTY_EDIT_DRAFT)
    setStatusMessage(null)
    setWritingExamplesContextFilter(filter)
  }

  function handleAnalyze() {
    if (pendingRef.current || activeFilter === 'all') return
    setStatusMessage(null)
    const nextPending: PendingRequest = { id: analyzeWritingStyle(activeFilter), kind: 'analyze', clearContext: activeFilter }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleDelete(sample: WritingExampleSample) {
    if (pendingRef.current) return
    setStatusMessage(null)
    const nextPending: PendingRequest = {
      id: requestDeleteWritingSample(sample.id),
      kind: 'delete',
      markContexts: [sample.contextType],
    }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleDeleteAll() {
    if (pendingRef.current) return
    setStatusMessage(null)
    const markContexts = activeFilter === 'all'
      ? Array.from(new Set<string>([...CONCRETE_CONTEXT_OPTIONS.map((option) => option.value), ...samples.map((sample) => sample.contextType)]))
      : [activeFilter]
    const nextPending: PendingRequest = { id: requestDeleteAllWritingSamples(activeFilter), kind: 'deleteAll', markContexts }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleCopy(sample: WritingExampleSample) {
    copyWritingSampleToClipboard(sample.content)
    flashCopiedSample(sample.id)
  }

  function handleStartEdit(sample: WritingExampleSample) {
    if (pendingRef.current) return
    setExpandedSampleId(sample.id)
    setEditingSampleId(sample.id)
    setEditingDraft({ content: sample.content, contextType: sample.contextType, recipient: sample.recipient ?? '' })
    setStatusMessage(null)
  }

  function handleCancelEdit() {
    setEditingSampleId(null)
    setEditingDraft(EMPTY_EDIT_DRAFT)
  }

  function handleSaveEdit(sample: WritingExampleSample) {
    if (pendingRef.current || !editingDraft.content.trim() || !editingDraft.contextType) return
    setStatusMessage(null)
    const nextPending: PendingRequest = {
      id: requestUpdateWritingSample(sample.id, editingDraft.content, editingDraft.contextType, editingDraft.recipient.trim()),
      kind: 'update',
      markContexts: Array.from(new Set([sample.contextType, editingDraft.contextType])),
    }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleOpenAddForm() {
    if (pendingRef.current) return
    const contextType = activeFilter === 'all' ? 'email_reply' : activeFilter
    setAddDraft({ contextType, content: '', recipient: '' })
    setIsAddFormOpen(true)
    setStatusMessage(null)
  }

  function handleCancelAddForm() {
    setIsAddFormOpen(false)
    setAddDraft({ contextType: 'email_reply', content: '', recipient: '' })
  }

  function handleSubmitAddForm() {
    if (pendingRef.current || !addDraft.content.trim() || addDraft.contextType === 'all') return
    setStatusMessage(null)
    const recipient = addDraft.recipient.trim() || undefined
    const nextPending: PendingRequest = {
      id: requestAddWritingSample(addDraft.content, addDraft.contextType, recipient),
      kind: 'add',
      markContexts: [addDraft.contextType],
    }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleRetry() {
    setWritingExamplesContextFilter(activeFilter)
  }

  if (!hasLoaded && !loadError) {
    return <p className="writing-examples-status" role="status">Loading Writing Examples settings...</p>
  }

  if (loadError) {
    return (
      <div className="writing-examples-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={handleRetry}>Retry</button>
      </div>
    )
  }

  const busy = pending !== null

  return (
    <div className="writing-examples-shell">
      <p className="writing-examples-intro">Your accepted Dill outputs are saved as writing samples to personalize future suggestions.</p>

      <div className="writing-examples-filter-row" role="tablist" aria-label="Context Type">
        {FILTER_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={option.value === activeFilter}
            className={option.value === activeFilter ? 'writing-examples-filter-tab writing-examples-filter-tab-selected' : 'writing-examples-filter-tab'}
            onClick={() => handleFilterChange(option.value)}
            title={option.value !== 'all' && changedContexts.has(option.value) ? 'Samples changed since the last analysis' : undefined}
          >
            {option.label}
            {option.value !== 'all' && changedContexts.has(option.value) && (
              <span className="writing-examples-filter-tab-marker" aria-hidden="true" />
            )}
          </button>
        ))}
      </div>

      {activeFilter !== 'all' && (
        <section className="writing-examples-style-section" aria-labelledby="writing-examples-style-heading">
          <div className="writing-examples-style-header">
            <h2 id="writing-examples-style-heading">Writing Style Analysis</h2>
            <button type="button" className="secondary-button" disabled={busy} onClick={handleAnalyze}>
              {pending?.kind === 'analyze' ? 'Analyzing...' : 'Analyze'}
            </button>
          </div>
          {changedContexts.has(activeFilter) && (
            <div className="writing-examples-stale-notice" role="status">
              <p>Samples in this context changed since the last analysis. Reanalyze to update the style profile.</p>
              <div className="writing-examples-actions">
                <button type="button" className="primary-button" disabled={busy} onClick={handleAnalyze}>
                  {pending?.kind === 'analyze' ? 'Analyzing...' : 'Reanalyze'}
                </button>
              </div>
            </div>
          )}
          {styleProfile ? (
            <div className="writing-examples-style-details">
              <div className="writing-examples-style-metrics">
                <div className="writing-examples-style-metric">
                  <span className="writing-examples-style-metric-label">Formality</span>
                  <span className="writing-examples-style-metric-value">{formalityDescription(styleProfile.styleAttributes.formalityLevel)}</span>
                  <span className="writing-examples-style-metric-detail">{Math.round(styleProfile.styleAttributes.formalityLevel * 100)}%</span>
                </div>
                <div className="writing-examples-style-metric">
                  <span className="writing-examples-style-metric-label">Confidence</span>
                  <span className="writing-examples-style-metric-value">{confidenceDescription(styleProfile.confidence)}</span>
                  <span className="writing-examples-style-metric-detail">{styleProfile.sampleCount} samples</span>
                </div>
                <div className="writing-examples-style-metric">
                  <span className="writing-examples-style-metric-label">Sentence Length</span>
                  <span className="writing-examples-style-metric-value">{styleProfile.styleAttributes.avgSentenceLength.toFixed(1)} words</span>
                  <span className="writing-examples-style-metric-detail">{styleProfile.styleAttributes.paragraphStructure}</span>
                </div>
              </div>
              {styleProfile.styleAttributes.toneMarkers.length > 0 && (
                <div className="writing-examples-tone-row">
                  {styleProfile.styleAttributes.toneMarkers.map((tone) => <span key={tone} className="writing-examples-tone-chip">{tone}</span>)}
                </div>
              )}
              {styleProfile.styleAttributes.styleSummary && <p className="writing-examples-style-summary">{plainMarkdownText(styleProfile.styleAttributes.styleSummary)}</p>}
            </div>
          ) : (
            <p className="writing-examples-empty">No style analysis yet. Save more samples and click Analyze.</p>
          )}
        </section>
      )}

      <section className="writing-examples-samples-section" aria-labelledby="writing-examples-samples-heading">
        <div className="writing-examples-samples-header">
          <h2 id="writing-examples-samples-heading">Samples</h2>
          <div className="writing-examples-samples-actions">
            <button type="button" className="secondary-button" disabled={busy} onClick={isAddFormOpen ? handleCancelAddForm : handleOpenAddForm}>
              {isAddFormOpen ? 'Cancel' : 'Add Sample'}
            </button>
            <button type="button" className="writing-examples-delete-all-button" disabled={busy || samples.length === 0} onClick={handleDeleteAll}>
              {pending?.kind === 'deleteAll' ? 'Deleting...' : 'Delete All Samples'}
            </button>
          </div>
        </div>

        {isAddFormOpen && (
          <div className="writing-examples-add-form">
            <div className="writing-examples-field">
              <span className="writing-examples-field-label">Context</span>
              <TokenizedSelect
                className="writing-examples-context-select"
                ariaLabel="New sample context"
                value={addDraft.contextType}
                options={CONCRETE_CONTEXT_OPTIONS}
                onValueChange={(contextType) => setAddDraft((current) => ({ ...current, contextType }))}
              />
            </div>
            <div className="writing-examples-field">
              <label htmlFor="writing-examples-add-recipient">Recipients (optional)</label>
              <RecipientChipsInput
                id="writing-examples-add-recipient"
                value={addDraft.recipient}
                onChange={(recipient) => setAddDraft((current) => ({ ...current, recipient }))}
              />
            </div>
            <div className="writing-examples-field">
              <label htmlFor="writing-examples-add-content">Content</label>
              <textarea
                id="writing-examples-add-content"
                className="writing-examples-textarea"
                rows={5}
                value={addDraft.content}
                onChange={(event) => setAddDraft((current) => ({ ...current, content: event.target.value }))}
                autoFocus
              />
            </div>
            <div className="writing-examples-actions">
              <button type="button" className="primary-button" disabled={busy || !addDraft.content.trim()} onClick={handleSubmitAddForm}>
                {pending?.kind === 'add' ? 'Saving...' : 'Save Sample'}
              </button>
            </div>
          </div>
        )}

        {isLoadingSamples && samples.length === 0 ? (
          <p className="writing-examples-status" role="status">Loading writing samples...</p>
        ) : samples.length === 0 ? (
          <p className="writing-examples-empty">No writing samples found. Writing samples will appear here after you accept Dill outputs, or you can add one with Add Sample.</p>
        ) : (
          <ul className="writing-examples-list basil-refresh-region" aria-busy={isLoadingSamples ? true : undefined}>
            {samples.map((sample) => (
              <li key={sample.id} className="writing-examples-list-row">
                <div className="writing-examples-list-header">
                  <span className="writing-examples-list-date">{formatCreatedAt(sample.createdAt)}</span>
                  <span className="writing-examples-context-badge">{contextDisplayName(sample.contextType)}</span>
                </div>
                {editingSampleId === sample.id ? (
                  <div className="writing-examples-edit-form">
                    <div className="writing-examples-edit-fields">
                      <div className="writing-examples-field">
                        <span className="writing-examples-field-label">Context</span>
                        <TokenizedSelect
                          className="writing-examples-context-select"
                          ariaLabel="Sample context"
                          value={editingDraft.contextType}
                          options={editContextOptions(sample.contextType)}
                          disabled={busy}
                          onValueChange={(contextType) => setEditingDraft((current) => ({ ...current, contextType }))}
                        />
                      </div>
                      <div className="writing-examples-field">
                        <label htmlFor={`writing-examples-edit-recipient-${sample.id}`}>Recipients (optional)</label>
                        <RecipientChipsInput
                          id={`writing-examples-edit-recipient-${sample.id}`}
                          value={editingDraft.recipient}
                          disabled={busy}
                          onChange={(recipient) => setEditingDraft((current) => ({ ...current, recipient }))}
                        />
                      </div>
                    </div>
                    <textarea
                      className="writing-examples-textarea"
                      aria-label="Edit writing sample"
                      rows={5}
                      value={editingDraft.content}
                      onChange={(event) => setEditingDraft((current) => ({ ...current, content: event.target.value }))}
                      autoFocus
                    />
                  </div>
                ) : (
                  <WritingSampleMarkdown content={sample.content} collapsed={expandedSampleId !== sample.id} />
                )}
                {editingSampleId !== sample.id && sample.recipient && <RecipientChipList recipient={sample.recipient} />}
                <div className="writing-examples-list-actions">
                  {editingSampleId === sample.id ? (
                    <>
                      <button type="button" className="secondary-button" disabled={busy} onClick={handleCancelEdit}>Cancel</button>
                      <button type="button" className="primary-button" disabled={busy || !editingDraft.content.trim()} onClick={() => handleSaveEdit(sample)}>
                        {pending?.kind === 'update' ? 'Saving...' : 'Save'}
                      </button>
                    </>
                  ) : (
                    <>
                      <button type="button" className="secondary-button" onClick={() => setExpandedSampleId((current) => (current === sample.id ? null : sample.id))}>
                        {expandedSampleId === sample.id ? 'Show Less' : 'View Full Text'}
                      </button>
                      <button type="button" className="secondary-button" onClick={() => handleCopy(sample)}>
                        {copiedSampleId === sample.id ? 'Copied' : 'Copy'}
                      </button>
                      <button type="button" className="secondary-button" disabled={busy} onClick={() => handleStartEdit(sample)}>Edit</button>
                      <button type="button" className="writing-examples-delete-button" disabled={busy} onClick={() => handleDelete(sample)}>
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {statusMessage && (
          <p className={statusMessage.isError ? 'writing-examples-status-error' : 'writing-examples-status-info'} role={statusMessage.isError ? 'alert' : 'status'}>
            {statusMessage.text}
          </p>
        )}
      </section>
    </div>
  )
}
