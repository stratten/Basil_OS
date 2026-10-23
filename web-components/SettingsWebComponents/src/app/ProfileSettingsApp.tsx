import { useEffect, useRef, useState } from 'react'
import TokenizedSelect from '@shared/TokenizedSelect'
import { notifyProfileSettingsReady, onProfileEvent, requestClearProfile, saveProfile } from '../services/profileBridge'
import type { ProfileFields, ProfileFormality, ProfileTone } from '../types'
import { MacContactsSettingsCard } from '../components/MacContactsSettingsCard'

const EMPTY_FIELDS: ProfileFields = {
  fullName: null,
  preferredName: null,
  email: null,
  jobTitle: null,
  companyName: null,
  industry: null,
  formality: null,
  tone: null,
  customInstructions: null,
}

const FORMALITY_OPTIONS: { value: ProfileFormality; label: string }[] = [
  { value: 'casual', label: 'Casual' },
  { value: 'professional', label: 'Professional' },
  { value: 'formal', label: 'Formal' },
]

const TONE_OPTIONS: { value: ProfileTone; label: string }[] = [
  { value: 'friendly', label: 'Friendly' },
  { value: 'business', label: 'Business' },
  { value: 'technical', label: 'Technical' },
  { value: 'warm', label: 'Warm' },
  { value: 'direct', label: 'Direct' },
  { value: 'conversational', label: 'Conversational' },
]

type PendingKind = 'save' | 'clear'

export function ProfileSettingsApp() {
  const [fields, setFields] = useState<ProfileFields | null>(null)
  const [draft, setDraft] = useState<ProfileFields>(EMPTY_FIELDS)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [pending, setPending] = useState<{ id: string; kind: PendingKind } | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const pendingRef = useRef(pending)
  pendingRef.current = pending

  useEffect(() => {
    const unsubscribe = onProfileEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setFields(event.profile)
        setDraft(event.profile)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRef.current?.id) {
        const kind = pendingRef.current?.kind
        pendingRef.current = null
        setPending(null)
        if (event.status === 'error') {
          setRequestError(event.message ?? 'Failed to update profile.')
        } else {
          setRequestError(null)
          if (kind === 'save' && event.status === 'success') {
            setSaveSuccess(true)
          }
        }
      }
    })
    notifyProfileSettingsReady()
    return unsubscribe
  }, [])

  function updateDraft<K extends keyof ProfileFields>(key: K, value: ProfileFields[K]) {
    setSaveSuccess(false)
    setDraft((current) => ({ ...current, [key]: value }))
  }

  function handleSave() {
    if (pendingRef.current) return
    setRequestError(null)
    setSaveSuccess(false)
    const nextPending = { id: saveProfile(draft), kind: 'save' } as const
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  function handleClear() {
    if (pendingRef.current) return
    setRequestError(null)
    setSaveSuccess(false)
    const nextPending = { id: requestClearProfile(), kind: 'clear' } as const
    pendingRef.current = nextPending
    setPending(nextPending)
  }

  if (!fields && !loadError) {
    return <p className="profile-settings-status" role="status">Loading Profile settings...</p>
  }

  if (loadError) {
    return (
      <div className="profile-settings-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyProfileSettingsReady()}>Retry</button>
      </div>
    )
  }

  const busy = pending !== null

  return (
    <div className="profile-settings-shell">
      <p className="profile-settings-intro">Help Basil personalize your experience by providing information about yourself.</p>

      <div className="profile-settings-columns">
        <section className="profile-settings-section" aria-labelledby="profile-identity-heading">
          <h2 id="profile-identity-heading">Identity</h2>
          <label className="profile-settings-field">
            <span>Full Name</span>
            <input type="text" value={draft.fullName ?? ''} disabled={busy} onChange={(e) => updateDraft('fullName', e.target.value || null)} placeholder="Your full name" />
          </label>
          <label className="profile-settings-field">
            <span>Preferred Name</span>
            <input type="text" value={draft.preferredName ?? ''} disabled={busy} onChange={(e) => updateDraft('preferredName', e.target.value || null)} placeholder="How you'd like to be addressed" />
          </label>
          <label className="profile-settings-field">
            <span>Email</span>
            <input type="text" value={draft.email ?? ''} disabled={busy} onChange={(e) => updateDraft('email', e.target.value || null)} placeholder="your.email@example.com" />
          </label>
        </section>

        <section className="profile-settings-section" aria-labelledby="profile-professional-heading">
          <h2 id="profile-professional-heading">Professional Context</h2>
          <label className="profile-settings-field">
            <span>Job Title</span>
            <input type="text" value={draft.jobTitle ?? ''} disabled={busy} onChange={(e) => updateDraft('jobTitle', e.target.value || null)} placeholder="Your job title" />
          </label>
          <label className="profile-settings-field">
            <span>Company</span>
            <input type="text" value={draft.companyName ?? ''} disabled={busy} onChange={(e) => updateDraft('companyName', e.target.value || null)} placeholder="Your company name" />
          </label>
          <label className="profile-settings-field">
            <span>Industry</span>
            <input type="text" value={draft.industry ?? ''} disabled={busy} onChange={(e) => updateDraft('industry', e.target.value || null)} placeholder="Your industry" />
          </label>
        </section>
      </div>

      <MacContactsSettingsCard />

      <section className="profile-settings-section" aria-labelledby="profile-communication-heading">
        <h2 id="profile-communication-heading">Communication Preferences</h2>
        <div className="profile-settings-columns">
          <label className="profile-settings-field">
            <span>Default Formality</span>
            <TokenizedSelect className="profile-settings-select" value={draft.formality ?? ''} disabled={busy} ariaLabel="Default Formality" onValueChange={(value) => updateDraft('formality', (value || null) as ProfileFormality | null)} options={[{ value: '', label: 'Not Set' }, ...FORMALITY_OPTIONS.map((option) => ({ value: option.value, label: option.label }))]} />
          </label>
          <label className="profile-settings-field">
            <span>Default Tone</span>
            <TokenizedSelect className="profile-settings-select" value={draft.tone ?? ''} disabled={busy} ariaLabel="Default Tone" onValueChange={(value) => updateDraft('tone', (value || null) as ProfileTone | null)} options={[{ value: '', label: 'Not Set' }, ...TONE_OPTIONS.map((option) => ({ value: option.value, label: option.label }))]} />
          </label>
        </div>
        <label className="profile-settings-field">
          <span>Custom Instructions</span>
          <textarea
            className="profile-settings-textarea"
            value={draft.customInstructions ?? ''}
            disabled={busy}
            maxLength={4000}
            rows={4}
            onChange={(e) => updateDraft('customInstructions', e.target.value || null)}
            placeholder={'e.g. "Do not use em dashes." "Minimize exclamation points." "Use typographic quotes, not straight quotes."'}
          />
          <span className="profile-settings-field-hint">Standing style/formatting preferences applied whenever Basil personalizes a response for you.</span>
        </label>
      </section>

      <div className="profile-settings-actions">
        <button type="button" className="primary-button" disabled={busy} onClick={handleSave}>
          {pending?.kind === 'save' ? 'Saving...' : saveSuccess ? 'Saved!' : 'Save Profile'}
        </button>
        <button type="button" className="profile-settings-clear-button" disabled={busy} onClick={handleClear}>
          {pending?.kind === 'clear' ? 'Clearing...' : 'Clear All'}
        </button>
      </div>

      {requestError && <p className="profile-settings-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
