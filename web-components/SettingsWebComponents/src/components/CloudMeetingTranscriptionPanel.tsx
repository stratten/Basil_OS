import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import PresenceRegion from '@shared/PresenceRegion'
import { Switch } from '@shared/Switch'
import {
  MIN_API_KEY_LENGTH,
  parseCloudTranscriptionState,
  type CloudCheckResult,
  type CloudConnection,
  type CloudProviderId,
  type CloudSettingsPatch,
  type CloudTranscriptionState,
} from '@shared/cloudTranscriptionTypes'
import {
  notifyCloudTranscriptionReady,
  onCloudTranscriptionEvent,
  requestCheckCloudConnection,
  requestRemoveCloudKey,
  requestSaveCloudKey,
  requestUpdateCloudSettings,
} from '../services/cloudTranscriptionBridge'
import { useOptimisticSettings } from '../app/useOptimisticSettings'

const DISCLOSURE =
  'When a recording uses a cloud service, live meeting audio is sent to that service so it can be transcribed. Basil still keeps the full recording on this Mac, and the local model takes over if the service stops. The service is billed by its provider under its own terms. Nothing is sent unless you choose a cloud service for a recording.'

type KeyAction = 'save' | 'remove' | 'check'

// The last state the host confirmed. A remount (switching Settings tabs) shows it at once and refreshes in the background instead of flashing a loading message.
let lastKnownState: CloudTranscriptionState | null = null

export function resetCloudMeetingTranscriptionCache() {
  lastKnownState = null
}

function Collapse({ open, children }: { open: boolean; children: ReactNode }) {
  return (
    <PresenceRegion visible={open} className="basil-presence cloud-meeting-transcription-collapse" settleWithoutTransition>
      <div className="cloud-meeting-transcription-collapse-inner">{children}</div>
    </PresenceRegion>
  )
}

function optimisticState(state: CloudTranscriptionState, patch: CloudSettingsPatch): CloudTranscriptionState {
  return {
    ...state,
    ...(patch.enabled !== undefined ? { enabled: patch.enabled } : {}),
    ...(patch.provider !== undefined ? { provider: patch.provider } : {}),
    ...(patch.connection !== undefined ? { connection: patch.connection } : {}),
    ...(patch.acknowledge_disclosure ? { acknowledged: true } : {}),
  }
}

export function CloudMeetingTranscriptionPanel() {
  const { settings: state, setSettings, track, receiveSnapshot, resolveIntent } = useOptimisticSettings<CloudTranscriptionState>()
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [checkResult, setCheckResult] = useState<CloudCheckResult | null>(null)
  const [keyBusy, setKeyBusy] = useState<KeyAction | null>(null)
  const [understood, setUnderstood] = useState(false)
  const [keyDraft, setKeyDraft] = useState('')
  const [settled, setSettled] = useState(false)
  const keyRequestRef = useRef<{ id: string; kind: KeyAction } | null>(null)
  const namePrefix = useId()

  useLayoutEffect(() => {
    if (lastKnownState !== null) receiveSnapshot(lastKnownState)
  }, [])

  useEffect(() => {
    const unsubscribe = onCloudTranscriptionEvent((event) => {
      if (event.type === 'state') {
        const parsed = parseCloudTranscriptionState(event.state)
        if (parsed === null) {
          setLoadError('Basil returned cloud transcription settings it could not read.')
          return
        }
        lastKnownState = parsed
        receiveSnapshot(parsed)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      const outcome = resolveIntent(event.requestId, event.status)
      if (outcome === 'error') {
        setActionError(event.message ?? 'Could not change the cloud transcription setting.')
        return
      }
      if (outcome === 'success') return
      const current = keyRequestRef.current
      if (current === null || current.id !== event.requestId) return
      keyRequestRef.current = null
      setKeyBusy(null)
      if (current.kind === 'check') {
        setCheckResult({ ok: event.status === 'success', message: event.message ?? (event.status === 'success' ? 'Connected.' : 'The connection check failed.') })
        return
      }
      if (event.status === 'error') {
        setActionError(event.message ?? 'Could not change the cloud transcription setting.')
        return
      }
      if (current.kind === 'save') setKeyDraft('')
    })
    notifyCloudTranscriptionReady()
    return unsubscribe
  }, [])

  const isLoaded = state !== null
  useEffect(() => {
    if (!isLoaded) return
    let inner = 0
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => setSettled(true))
    })
    return () => {
      cancelAnimationFrame(outer)
      cancelAnimationFrame(inner)
    }
  }, [isLoaded])

  function update(patch: CloudSettingsPatch) {
    if (state === null) return
    setActionError(null)
    setSettings(optimisticState(state, patch))
    track(requestUpdateCloudSettings(patch))
  }

  function beginKeyAction(kind: KeyAction, send: () => string) {
    if (keyRequestRef.current !== null) return
    setActionError(null)
    if (kind !== 'check') setCheckResult(null)
    keyRequestRef.current = { id: send(), kind }
    setKeyBusy(kind)
  }

  if (state === null) {
    if (loadError === null) return <p className="transcription-api-models-status" role="status">Loading cloud meeting transcription...</p>
    return (
      <div className="transcription-api-models-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={notifyCloudTranscriptionReady}>Retry</button>
      </div>
    )
  }

  const selected = state.providers.find((provider) => provider.id === state.provider) ?? state.providers[0]
  const ownKey = state.connection === 'own_key'
  const needsDisclosure = !state.acknowledged && !understood

  const chooseConnection = (connection: CloudConnection) => update({ connection })
  const chooseProvider = (provider: CloudProviderId) => {
    setKeyDraft('')
    setCheckResult(null)
    update({ provider })
  }

  return (
    <section className="cloud-meeting-transcription" aria-label="Cloud meeting transcription" data-settled={settled ? 'true' : 'false'}>
      <div className="transcription-api-models-provider-header">
        <span className="transcription-api-models-provider-name">Cloud Meeting Transcription</span>
      </div>
      <p className="cloud-meeting-transcription-disclosure">{DISCLOSURE}</p>
      <Collapse open={!state.acknowledged}>
        <label className="cloud-meeting-transcription-choice">
          <input
            type="checkbox"
            checked={understood}
            onChange={(event) => {
              setUnderstood(event.target.checked)
              if (event.target.checked) update({ acknowledge_disclosure: true })
            }}
          />
          I understand that live meeting audio will be sent to the service I choose.
        </label>
      </Collapse>
      <fieldset className="cloud-meeting-transcription-group">
        <legend>Connection</legend>
        <label className="cloud-meeting-transcription-choice">
          <input type="radio" name={`${namePrefix}-connection`} checked={ownKey} onChange={() => chooseConnection('own_key')} />
          My own API key (words appear as people speak)
        </label>
        <label className="cloud-meeting-transcription-choice">
          <input type="radio" name={`${namePrefix}-connection`} checked={!ownKey} onChange={() => chooseConnection('basil_account')} />
          My Basil account (updates every few seconds)
        </label>
        <Collapse open={!ownKey && !state.account_available}>
          <p className="transcription-api-models-status">Sign in to Basil to use your account.</p>
        </Collapse>
      </fieldset>
      <Collapse open={ownKey}>
        <fieldset className="cloud-meeting-transcription-group">
          <legend>Service</legend>
          {state.providers.map((provider) => (
            <label key={provider.id} className="cloud-meeting-transcription-choice">
              <input type="radio" name={`${namePrefix}-provider`} checked={provider.id === state.provider} onChange={() => chooseProvider(provider.id)} />
              {provider.label}
              {provider.has_key ? ' (key saved)' : ''}
            </label>
          ))}
          <div className="transcription-api-models-key-row">
            <input
              type="password"
              className="transcription-api-models-key-input"
              autoComplete="off"
              spellCheck={false}
              aria-label={`${selected.label} API key`}
              placeholder={selected.has_key ? `Update ${selected.label} API Key` : `Enter ${selected.label} API Key`}
              value={keyDraft}
              maxLength={512}
              onChange={(event) => setKeyDraft(event.target.value)}
            />
            <button
              type="button"
              className="secondary-button"
              disabled={keyBusy !== null || keyDraft.trim().length < MIN_API_KEY_LENGTH}
              onClick={() => beginKeyAction('save', () => requestSaveCloudKey(selected.id, keyDraft.trim()))}
            >
              {selected.has_key ? 'Update Key' : 'Save Key'}
            </button>
          </div>
          <div className="transcription-api-models-key-row">
            <button
              type="button"
              className="secondary-button"
              disabled={keyBusy !== null || !selected.has_key}
              onClick={() => beginKeyAction('check', () => requestCheckCloudConnection(selected.id))}
            >
              {keyBusy === 'check' ? 'Testing...' : 'Test Connection'}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={keyBusy !== null || !selected.has_key}
              onClick={() => beginKeyAction('remove', () => requestRemoveCloudKey(selected.id))}
            >
              Remove Key
            </button>
          </div>
          <Collapse open={checkResult !== null}>
            <p className={checkResult?.ok ? 'transcription-api-models-status-success' : 'transcription-api-models-status-error'} role={checkResult?.ok ? 'status' : 'alert'}>
              {checkResult?.message}
            </p>
          </Collapse>
        </fieldset>
      </Collapse>
      <Switch
        id="cloud-meeting-transcription-toggle"
        checked={state.enabled}
        disabled={!state.enabled && needsDisclosure}
        onChange={(enabled) => update({ enabled, ...(enabled && understood ? { acknowledge_disclosure: true } : {}) })}
        label="Use cloud transcription by default"
      />
      <p className="transcription-api-models-status">A service with a saved key stays in the Notetaker's model menu either way, so you can pick it for a single recording. Turn this on only to start every recording on the service above.</p>
      <Collapse open={!state.enabled && needsDisclosure}>
        <p className="transcription-api-models-status">Confirm the statement above first.</p>
      </Collapse>
      <Collapse open={actionError !== null}>
        <p className="transcription-api-models-status-error" role="alert">
          {actionError}
        </p>
      </Collapse>
    </section>
  )
}
