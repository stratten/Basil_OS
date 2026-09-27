import { useEffect, useRef, useState } from 'react'
import {
  analyzeWritingStyle,
  copyWritingSampleToClipboard,
  notifyWritingExamplesSettingsReady,
  onWritingExamplesEvent,
  requestDeleteAllWritingSamples,
  requestDeleteWritingSample,
  setWritingExamplesContextFilter,
} from '../services/writingExamplesBridge'
import type { WritingExampleSample, WritingExampleStyleProfile, WritingExamplesContextFilter } from '../types'

interface PendingRequest {
  id: string
  kind: 'delete' | 'deleteAll' | 'analyze'
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

function contextDisplayName(contextType: string): string {
  return FILTER_OPTIONS.find((option) => option.value === contextType)?.label ?? contextType.replace(/_/g, ' ')
}

function formatCreatedAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function contentPreview(content: string): string {
  const maxLength = 100
  return content.length <= maxLength ? content : `${content.slice(0, maxLength)}...`
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
  const [copiedSampleId, setCopiedSampleId] = useState<string | null>(null)
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
        pendingRef.current = null
        setPending(null)
        if (event.status === 'cancelled') {
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
    setStatusMessage(null)
    setWritingExamplesContextFilter(filter)
  }

  function handleAnalyze() {
    if (pendingRef.current || activeFilter === 'all') return
    setStatusMessage(null)
    const nextPending: PendingRequest = { id: analyzeWritingStyle(activeFilter), kind: 'analyze' }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleDelete(sampleId: string) {
    if (pendingRef.current) return
    setStatusMessage(null)
    const nextPending: PendingRequest = { id: requestDeleteWritingSample(sampleId), kind: 'delete' }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleDeleteAll() {
    if (pendingRef.current) return
    setStatusMessage(null)
    const nextPending: PendingRequest = { id: requestDeleteAllWritingSamples(activeFilter), kind: 'deleteAll' }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleCopy(sample: WritingExampleSample) {
    copyWritingSampleToClipboard(sample.content)
    setCopiedSampleId(sample.id)
    setTimeout(() => setCopiedSampleId((current) => (current === sample.id ? null : current)), 1200)
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
      <p className="writing-examples-intro">Your accepted AssistantSessions are saved as writing samples to personalize future suggestions.</p>

      <div className="writing-examples-filter-row" role="tablist" aria-label="Context Type">
        {FILTER_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={option.value === activeFilter}
            className={option.value === activeFilter ? 'writing-examples-filter-tab writing-examples-filter-tab-selected' : 'writing-examples-filter-tab'}
            onClick={() => handleFilterChange(option.value)}
          >
            {option.label}
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
              {styleProfile.styleAttributes.styleSummary && <p className="writing-examples-style-summary">{styleProfile.styleAttributes.styleSummary}</p>}
            </div>
          ) : (
            <p className="writing-examples-empty">No style analysis yet. Save more samples and click Analyze.</p>
          )}
        </section>
      )}

      <section className="writing-examples-samples-section" aria-labelledby="writing-examples-samples-heading">
        <div className="writing-examples-samples-header">
          <h2 id="writing-examples-samples-heading">Samples</h2>
          <button type="button" className="writing-examples-delete-all-button" disabled={busy || samples.length === 0} onClick={handleDeleteAll}>
            {pending?.kind === 'deleteAll' ? 'Deleting...' : 'Delete All Samples'}
          </button>
        </div>

        {isLoadingSamples ? (
          <p className="writing-examples-status" role="status">Loading writing samples...</p>
        ) : samples.length === 0 ? (
          <p className="writing-examples-empty">No writing samples found. Writing samples will appear here after you accept AssistantSessions.</p>
        ) : (
          <ul className="writing-examples-list">
            {samples.map((sample) => (
              <li key={sample.id} className="writing-examples-list-row">
                <div className="writing-examples-list-header">
                  <span className="writing-examples-list-date">{formatCreatedAt(sample.createdAt)}</span>
                  <span className="writing-examples-context-badge">{contextDisplayName(sample.contextType)}</span>
                </div>
                <p className="writing-examples-list-preview">{expandedSampleId === sample.id ? sample.content : contentPreview(sample.content)}</p>
                {sample.recipient && <p className="writing-examples-list-recipient">To: {sample.recipient}</p>}
                <div className="writing-examples-list-actions">
                  <button type="button" className="secondary-button" onClick={() => setExpandedSampleId((current) => (current === sample.id ? null : sample.id))}>
                    {expandedSampleId === sample.id ? 'Show Less' : 'View Full Text'}
                  </button>
                  <button type="button" className="secondary-button" onClick={() => handleCopy(sample)}>
                    {copiedSampleId === sample.id ? 'Copied' : 'Copy'}
                  </button>
                  <button type="button" className="writing-examples-delete-button" disabled={busy} onClick={() => handleDelete(sample.id)}>
                    Delete
                  </button>
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
