import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import {
  declineMemoryProposal,
  notifyMemoryIntelligenceSettingsReady,
  onMemoryIntelligenceEvent,
  openMemoryFile,
  openMemoryProposal,
  runMemoryIntelligenceNow,
  updateMemorySetting,
} from '../services/memoryIntelligenceBridge'
import type { MemoryDocument, MemoryIntelligenceSettings, MemoryProposal, MemoryReasoningModelOption, MemorySettingField } from '../types'

interface PendingRequest {
  id: string
  kind: 'settings' | 'runNow' | 'decline'
}

interface StatusMessage {
  text: string
  isError: boolean
}

function cadenceSummary(settings: MemoryIntelligenceSettings): string {
  const parts: string[] = []
  if (settings.memoryAfterTaskEnabled) parts.push('after completed work')
  if (settings.memoryDailyEnabled) parts.push(`daily at ${settings.memoryDailyTimeLocal}`)
  if (parts.length === 0) return 'Off. Basil will not propose memory updates unless you enable it.'
  return `Runs ${parts.join(' and ')}. All writes still require approval.`
}

function formatDocumentSize(document: MemoryDocument): string {
  if (document.capBytes && document.capBytes > 0) {
    return `${document.sizeBytes} / ${document.capBytes} bytes`
  }
  return `${document.sizeBytes} bytes`
}

export function MemoryIntelligenceSettingsApp() {
  const [settings, setSettings] = useState<MemoryIntelligenceSettings | null>(null)
  const [proposals, setProposals] = useState<MemoryProposal[]>([])
  const [documents, setDocuments] = useState<MemoryDocument[]>([])
  const [availableModels, setAvailableModels] = useState<MemoryReasoningModelOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<StatusMessage | null>(null)
  const [pending, setPending] = useState<PendingRequest | null>(null)
  const pendingRef = useRef<PendingRequest | null>(null)
  pendingRef.current = pending

  useEffect(() => {
    const unsubscribe = onMemoryIntelligenceEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setSettings(event.settings)
        setProposals(event.proposals)
        setDocuments(event.documents)
        setAvailableModels(event.availableModels)
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
        setStatusMessage(event.message ? { text: event.message, isError: event.status === 'error' } : event.status === 'error' ? { text: 'Failed to update memory settings.', isError: true } : null)
      }
    })
    notifyMemoryIntelligenceSettingsReady()
    return unsubscribe
  }, [])

  function updateSetting(field: MemorySettingField, value: boolean | string | null) {
    if (pendingRef.current) return
    setStatusMessage(null)
    const nextPending: PendingRequest = { id: updateMemorySetting(field, value), kind: 'settings' }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleRunNow() {
    if (pendingRef.current) return
    setStatusMessage(null)
    const nextPending: PendingRequest = { id: runMemoryIntelligenceNow(), kind: 'runNow' }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleDecline(proposalId: string) {
    if (pendingRef.current) return
    setStatusMessage(null)
    const nextPending: PendingRequest = { id: declineMemoryProposal(proposalId), kind: 'decline' }
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  if (!settings && !loadError) {
    return <p className="memory-intelligence-status" role="status">Loading Personal Context settings...</p>
  }

  if (loadError) {
    return (
      <div className="memory-intelligence-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyMemoryIntelligenceSettingsReady()}>Retry</button>
      </div>
    )
  }

  const busy = pending !== null
  const evaluatorModelOptions = settings!.memoryProcessingModel && !availableModels.some((model) => model.id === settings!.memoryProcessingModel)
    ? [{ id: settings!.memoryProcessingModel, displayName: `${settings!.memoryProcessingModel} (unavailable)` }, ...availableModels]
    : availableModels

  return (
    <div className="memory-intelligence-shell">
      <section className="memory-intelligence-section" aria-labelledby="memory-intelligence-heading">
        <div className="memory-intelligence-section-header">
          <div>
            <h2 id="memory-intelligence-heading">Personal Context</h2>
            <p className="memory-intelligence-cadence">{cadenceSummary(settings!)}</p>
          </div>
          <button type="button" className="secondary-button" disabled={busy} onClick={handleRunNow}>
            {pending?.kind === 'runNow' ? 'Running...' : 'Run now'}
          </button>
        </div>

        <Switch
          id="memory-after-task-enabled"
          label="Evaluate completed work for memory proposals"
          checked={settings!.memoryAfterTaskEnabled}
          disabled={busy}
          onChange={(checked) => updateSetting('memoryAfterTaskEnabled', checked)}
        />
        <Switch
          id="memory-daily-enabled"
          label="Run daily memory review"
          checked={settings!.memoryDailyEnabled}
          disabled={busy}
          onChange={(checked) => updateSetting('memoryDailyEnabled', checked)}
        />

        <div className="memory-intelligence-row">
          <label className="memory-intelligence-field">
            <span>Daily time</span>
            <input
              type="time"
              value={settings!.memoryDailyTimeLocal}
              disabled={busy || !settings!.memoryDailyEnabled}
              onChange={(e) => updateSetting('memoryDailyTimeLocal', e.target.value)}
            />
          </label>
          <label className="memory-intelligence-field">
            <span>Evaluator model</span>
            <TokenizedSelect
              className="memory-intelligence-select"
              value={settings!.memoryProcessingModel ?? ''}
              disabled={busy}
              ariaLabel="Evaluator model"
              onValueChange={(value) => updateSetting('memoryProcessingModel', value || null)}
              options={[
                { value: '', label: 'Default reasoning model' },
                ...evaluatorModelOptions.map((model) => ({ value: model.id, label: model.displayName })),
              ]}
            />
          </label>
        </div>

        {statusMessage && (
          <p className={statusMessage.isError ? 'memory-intelligence-status-error' : 'memory-intelligence-status-info'} role={statusMessage.isError ? 'alert' : 'status'}>
            {statusMessage.text}
          </p>
        )}
      </section>

      <section className="memory-intelligence-section" aria-labelledby="memory-proposals-heading">
        <h2 id="memory-proposals-heading">Pending Memory Proposals</h2>
        {proposals.length === 0 ? (
          <p className="memory-intelligence-empty">No pending proposals.</p>
        ) : (
          <ul className="memory-intelligence-list">
            {proposals.map((proposal) => (
              <li key={proposal.id} className="memory-intelligence-list-row">
                <div className="memory-intelligence-list-main">
                  <span className="memory-intelligence-list-title">{proposal.targetFileName}</span>
                  <span className="memory-intelligence-list-detail">{proposal.entry}</span>
                  <span className="memory-intelligence-list-meta">{proposal.why ?? 'Pending review'} · {proposal.confidence ?? '-'} · {proposal.createdAt}</span>
                </div>
                <div className="memory-intelligence-list-actions">
                  <button type="button" className="secondary-button" onClick={() => openMemoryProposal(proposal.id)}>Open</button>
                  <button type="button" className="memory-intelligence-decline-button" disabled={busy} onClick={() => handleDecline(proposal.id)}>
                    {pending?.kind === 'decline' ? 'Declining...' : 'Decline'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="memory-intelligence-section" aria-labelledby="memory-files-heading">
        <h2 id="memory-files-heading">Memory Files</h2>
        {documents.length === 0 ? (
          <p className="memory-intelligence-empty">No memory files found.</p>
        ) : (
          <ul className="memory-intelligence-list">
            {documents.map((document) => (
              <li key={document.fileName} className="memory-intelligence-list-row">
                <div className="memory-intelligence-list-main">
                  <span className="memory-intelligence-list-title">{document.fileName}</span>
                  <span className="memory-intelligence-list-meta">{formatDocumentSize(document)} · Updated {document.updatedAt ?? '-'}</span>
                </div>
                <div className="memory-intelligence-list-actions">
                  <button type="button" className="secondary-button" onClick={() => openMemoryFile(document.fileName)}>Open</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
