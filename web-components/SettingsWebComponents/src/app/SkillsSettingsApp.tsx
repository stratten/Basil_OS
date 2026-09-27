import { useEffect, useState } from 'react'
import { Switch } from '@shared/Switch'
import { SettingsSubTabs } from '@shared/SettingsSubTabs'
import TokenizedSelect from '@shared/TokenizedSelect'
import {
  focusReconciliationWorkspace,
  notifySkillsSettingsReady,
  onSkillsEvent,
  openReconciliationWorkspace,
  openSkill,
  openSkillCandidate,
  requestDeclineCandidate,
  requestDeleteSkill,
  requestRunIntelligenceNow,
  requestUpdateSkillAfterTaskEnabled,
  requestUpdateSkillDailyEnabled,
  requestUpdateSkillDailyTimeLocal,
  requestUpdateSkillProcessingModel,
  requestUpdateSkillReconciliationMinInstances,
} from '../services/skillsSettingsBridge'
import type { SkillCandidateSummary, SkillsInitEvent, SkillsSnapshotEvent } from '../types'

type SkillsState = Omit<SkillsInitEvent, 'type' | 'protocolVersion'>
type PendingAction = { kind: 'candidate' | 'skill' | 'run'; target?: string }
type CandidateSubTab = 'recurring' | 'singleSightings'

function candidateSubTabId(id: CandidateSubTab): string {
  return `skills-candidates-tab-${id}`
}

function candidateSubPanelId(id: CandidateSubTab): string {
  return `skills-candidates-panel-${id}`
}

function extractFields(event: SkillsInitEvent | SkillsSnapshotEvent): SkillsState {
  return {
    skillCandidates: event.skillCandidates,
    savedSkills: event.savedSkills,
    reconciliationActive: event.reconciliationActive,
    skillAfterTaskEnabled: event.skillAfterTaskEnabled,
    skillDailyEnabled: event.skillDailyEnabled,
    skillDailyTimeLocal: event.skillDailyTimeLocal,
    skillProcessingModel: event.skillProcessingModel,
    skillReconciliationMinInstances: event.skillReconciliationMinInstances,
    availableSkillProcessingModels: event.availableSkillProcessingModels,
    pendingCandidateActionIDs: event.pendingCandidateActionIDs,
    pendingSkillDeletionSlugs: event.pendingSkillDeletionSlugs,
    isLoadingSkillsState: event.isLoadingSkillsState,
    isRunningSkillsIntelligence: event.isRunningSkillsIntelligence,
    statusMessage: event.statusMessage,
  }
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function removeId(ids: Set<string>, id: string): Set<string> {
  if (!ids.has(id)) return ids
  const next = new Set(ids)
  next.delete(id)
  return next
}

function cadenceSummary(state: SkillsState): string {
  const parts: string[] = []
  if (state.skillAfterTaskEnabled) parts.push('after successful work')
  if (state.skillDailyEnabled) parts.push(`daily at ${state.skillDailyTimeLocal}`)
  if (parts.length === 0) return 'Off. Basil will not propose reusable skills unless you enable it.'
  return `Runs ${parts.join(' and ')}. New skills still require approval.`
}

export function SkillsSettingsApp() {
  const [state, setState] = useState<SkillsState | null>(null)
  const [settingsPendingIds, setSettingsPendingIds] = useState<Set<string>>(new Set())
  const [pendingActions, setPendingActions] = useState<Map<string, PendingAction>>(new Map())
  const [isOpeningReconciliation, setIsOpeningReconciliation] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [selectedCandidateTab, setSelectedCandidateTab] = useState<CandidateSubTab>('recurring')

  useEffect(() => {
    const unsubscribe = onSkillsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setState(extractFields(event))
        setIsOpeningReconciliation(false)
        return
      }
      if (event.type === 'intentResult') {
        setSettingsPendingIds((prev) => removeId(prev, event.requestId))
        setPendingActions((prev) => {
          if (!prev.has(event.requestId)) return prev
          const next = new Map(prev)
          next.delete(event.requestId)
          return next
        })
        setRequestError(event.status === 'error' ? event.message ?? 'The request failed.' : null)
      }
    })
    notifySkillsSettingsReady()
    return unsubscribe
  }, [])

  function submitSetting(id: string) {
    setRequestError(null)
    setSettingsPendingIds((prev) => new Set(prev).add(id))
  }

  function submitAction(requestId: string, action: PendingAction) {
    setRequestError(null)
    setPendingActions((prev) => new Map(prev).set(requestId, action))
  }

  function requestCandidateDecline(candidateId: string) {
    const requestId = requestDeclineCandidate(candidateId)
    submitAction(requestId, { kind: 'candidate', target: candidateId })
  }

  function requestSkillDelete(slug: string) {
    const requestId = requestDeleteSkill(slug)
    submitAction(requestId, { kind: 'skill', target: slug })
  }

  function requestRunNow() {
    const requestId = requestRunIntelligenceNow()
    submitAction(requestId, { kind: 'run' })
  }

  function requestOpenReconciliationWorkspace() {
    setRequestError(null)
    setIsOpeningReconciliation(true)
    openReconciliationWorkspace()
  }

  function hasPendingAction(kind: PendingAction['kind'], target?: string) {
    return Array.from(pendingActions.values()).some((action) => action.kind === kind && action.target === target)
  }

  if (!state) {
    return <p className="skills-settings-status" role="status">Loading Skill Intelligence...</p>
  }

  const settingsDisabled = settingsPendingIds.size > 0
  const isRunNowPending = hasPendingAction('run')
  const localPendingCandidateIds = new Set(
    Array.from(pendingActions.values())
      .filter((action) => action.kind === 'candidate' && action.target)
      .map((action) => action.target!),
  )
  const evaluatorModelValue = state.skillProcessingModel ?? ''
  const recurringCandidates: SkillCandidateSummary[] = state.skillCandidates.filter(
    (candidate) => candidate.observationCount >= state.skillReconciliationMinInstances,
  )
  const singleSightingCandidates: SkillCandidateSummary[] = state.skillCandidates.filter(
    (candidate) => candidate.observationCount < state.skillReconciliationMinInstances,
  )

  return (
    <div className="skills-settings-shell">
      <section className="skills-settings-section" aria-labelledby="skills-intelligence-heading">
        <div className="skills-settings-header-row">
          <div>
            <h2 id="skills-intelligence-heading">Skill Intelligence</h2>
            <p className="skills-settings-field-hint">{cadenceSummary(state)}</p>
          </div>
          <div className="skills-settings-header-actions">
            <button
              type="button"
              className="secondary-button"
              disabled={state.reconciliationActive || isOpeningReconciliation}
              onClick={requestOpenReconciliationWorkspace}
            >
              Open Reconciliation Workspace
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={state.isRunningSkillsIntelligence || state.reconciliationActive || isRunNowPending}
              onClick={requestRunNow}
            >
              {state.isRunningSkillsIntelligence || isRunNowPending ? 'Running…' : 'Run now'}
            </button>
          </div>
        </div>

        <Switch
          id="skills-after-task-enabled"
          label="Evaluate completed work for reusable skills"
          checked={state.skillAfterTaskEnabled}
          disabled={settingsDisabled}
          onChange={(checked) => { setState({ ...state, skillAfterTaskEnabled: checked }); submitSetting(requestUpdateSkillAfterTaskEnabled(checked)) }}
        />
        <Switch
          id="skills-daily-enabled"
          label="Run daily skill review"
          checked={state.skillDailyEnabled}
          disabled={settingsDisabled}
          onChange={(checked) => { setState({ ...state, skillDailyEnabled: checked }); submitSetting(requestUpdateSkillDailyEnabled(checked)) }}
        />

        <div className="skills-settings-row">
          <label htmlFor="skills-daily-time">Daily time</label>
          <input
            id="skills-daily-time"
            type="time"
            value={state.skillDailyTimeLocal}
            disabled={settingsDisabled || !state.skillDailyEnabled}
            onChange={(event) => { setState({ ...state, skillDailyTimeLocal: event.target.value }); submitSetting(requestUpdateSkillDailyTimeLocal(event.target.value)) }}
          />
          <label htmlFor="skills-evaluator-model">Evaluator model</label>
          <TokenizedSelect
            value={evaluatorModelValue}
            disabled={settingsDisabled}
            ariaLabel="Evaluator model"
            onValueChange={(value) => {
              const next = value || null
              setState({ ...state, skillProcessingModel: next })
              submitSetting(requestUpdateSkillProcessingModel(next))
            }}
            options={[
              { value: '', label: 'Default reasoning model' },
              ...state.availableSkillProcessingModels.map((model) => ({ value: model.id, label: model.displayName })),
            ]}
          />
        </div>

        <div className="skills-settings-row">
          <label htmlFor="skills-reconciliation-threshold">Reconciliation threshold</label>
          <div className="skills-settings-stepper">
            <button
              type="button"
              className="secondary-button"
              disabled={settingsDisabled || state.reconciliationActive || state.skillReconciliationMinInstances <= 1}
              onClick={() => {
                const next = state.skillReconciliationMinInstances - 1
                setState({ ...state, skillReconciliationMinInstances: next })
                submitSetting(requestUpdateSkillReconciliationMinInstances(next))
              }}
            >
              -
            </button>
            <span id="skills-reconciliation-threshold">
              {state.skillReconciliationMinInstances} observation{state.skillReconciliationMinInstances === 1 ? '' : 's'}
            </span>
            <button
              type="button"
              className="secondary-button"
              disabled={settingsDisabled || state.reconciliationActive || state.skillReconciliationMinInstances >= 20}
              onClick={() => {
                const next = state.skillReconciliationMinInstances + 1
                setState({ ...state, skillReconciliationMinInstances: next })
                submitSetting(requestUpdateSkillReconciliationMinInstances(next))
              }}
            >
              +
            </button>
          </div>
          <p className="skills-settings-field-hint">Candidates seen fewer times are treated as single sightings and excluded from reconciliation.</p>
        </div>
      </section>
      <div className="skills-settings-lists-wrapper">
      <div
        className={state.reconciliationActive ? 'skills-settings-lists skills-settings-lists-locked' : 'skills-settings-lists'}
        aria-hidden={state.reconciliationActive}
      >
        <section className="skills-settings-section" aria-labelledby="skills-candidates-heading">
          <h2 id="skills-candidates-heading">Pending Skill Candidates</h2>
          {state.skillCandidates.length === 0 ? (
            <p className="skills-settings-field-hint">No pending skill candidates.</p>
          ) : (
            <>
              <SettingsSubTabs
                tabs={[
                  { id: 'recurring', label: `Recurring (${recurringCandidates.length})` },
                  { id: 'singleSightings', label: `Single Sightings (${singleSightingCandidates.length})` },
                ]}
                selected={selectedCandidateTab}
                onSelect={setSelectedCandidateTab}
                ariaLabel="Pending skill candidates"
                getTabId={candidateSubTabId}
                getPanelId={candidateSubPanelId}
              />
              <div
                id={candidateSubPanelId(selectedCandidateTab)}
                role="tabpanel"
                aria-labelledby={candidateSubTabId(selectedCandidateTab)}
              >
                {selectedCandidateTab === 'recurring' ? (
                  <CandidateGroup
                    title={`Seen ${state.skillReconciliationMinInstances}+ times, so these are included in reconciliation.`}
                    candidates={recurringCandidates}
                    emptyLabel="No recurring candidates yet."
                    pendingCandidateActionIDs={state.pendingCandidateActionIDs}
                    localPendingCandidateIds={localPendingCandidateIds}
                    onOpen={openSkillCandidate}
                    onDecline={requestCandidateDecline}
                  />
                ) : (
                  <CandidateGroup
                    title="Seen fewer times than the reconciliation threshold, so these are excluded from reconciliation until they recur."
                    candidates={singleSightingCandidates}
                    emptyLabel="No single-sighting candidates."
                    pendingCandidateActionIDs={state.pendingCandidateActionIDs}
                    localPendingCandidateIds={localPendingCandidateIds}
                    onOpen={openSkillCandidate}
                    onDecline={requestCandidateDecline}
                  />
                )}
              </div>
            </>
          )}
        </section>

        <section className="skills-settings-section" aria-labelledby="skills-saved-heading">
          <h2 id="skills-saved-heading">Saved Skills</h2>
          {state.savedSkills.length === 0 ? (
            <p className="skills-settings-field-hint">No saved skills yet.</p>
          ) : (
            <table className="skills-settings-table skills-settings-table-saved">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>When to use</th>
                  <th>Ver / Seen</th>
                  <th>Last used</th>
                  <th>Size</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {state.savedSkills.map((skill) => {
                  const isDeleting = state.pendingSkillDeletionSlugs.includes(skill.slug) || hasPendingAction('skill', skill.slug)
                  return (
                    <tr key={skill.slug}>
                      <td>{skill.title}</td>
                      <td>{skill.whenToUse}</td>
                      <td>v{skill.version} / {skill.observationCount}x</td>
                      <td>{skill.lastUsed ? formatTimestamp(skill.lastUsed) : '-'}</td>
                      <td>{skill.sizeBytes} / {skill.capBytes} bytes</td>
                      <td className="skills-settings-actions">
                        <button type="button" className="secondary-button" disabled={isDeleting} onClick={() => openSkill(skill.slug)}>Open</button>
                        <button
                          type="button"
                          className="secondary-button skills-settings-destructive"
                          disabled={isDeleting}
                          onClick={() => requestSkillDelete(skill.slug)}
                        >
                          {isDeleting ? 'Deleting…' : 'Delete'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </section>

      </div>
        {state.reconciliationActive && (
          <div className="skills-settings-lock-overlay">
            <p>Skill reconciliation is open in its own window</p>
            <p className="skills-settings-field-hint">This list is locked until you close the reconciliation workspace.</p>
            <button type="button" className="secondary-button skills-settings-show-workspace" onClick={() => focusReconciliationWorkspace()}>Show Workspace</button>
          </div>
        )}
      </div>

      {state.statusMessage && (
        <p
          className={state.statusMessage.includes('Error') ? 'skills-settings-inline-error' : 'skills-settings-status'}
          role={state.statusMessage.includes('Error') ? 'alert' : 'status'}
        >
          {state.statusMessage}
        </p>
      )}
      {requestError && requestError !== state.statusMessage && <p className="skills-settings-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}

function CandidateGroup({
  title,
  candidates,
  emptyLabel,
  pendingCandidateActionIDs,
  localPendingCandidateIds,
  onOpen,
  onDecline,
}: {
  title: string
  candidates: SkillCandidateSummary[]
  emptyLabel: string
  pendingCandidateActionIDs: string[]
  localPendingCandidateIds: ReadonlySet<string>
  onOpen: (id: string) => void
  onDecline: (id: string) => void
}) {
  return (
    <div className="skills-settings-candidate-group">
      <p className="skills-settings-field-hint">{title}</p>
      {candidates.length === 0 ? (
        <p className="skills-settings-field-hint">{emptyLabel}</p>
      ) : (
        <table className="skills-settings-table skills-settings-table-candidates">
          <thead>
            <tr>
              <th>Created</th>
              <th>Title</th>
              <th>When to use</th>
              <th>Seen</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => {
              const isDeclining = pendingCandidateActionIDs.includes(candidate.id) || localPendingCandidateIds.has(candidate.id)
              return (
                <tr key={candidate.id}>
                  <td>{formatTimestamp(candidate.createdAt)}</td>
                  <td>{candidate.title}</td>
                  <td>{candidate.whenToUse}</td>
                  <td>{candidate.observationCount}x</td>
                  <td className="skills-settings-actions">
                    <button type="button" className="secondary-button" onClick={() => onOpen(candidate.id)}>Open</button>
                    <button
                      type="button"
                      className="secondary-button skills-settings-destructive"
                      disabled={isDeclining}
                      onClick={() => onDecline(candidate.id)}
                    >
                      {isDeclining ? 'Declining…' : 'Decline'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
