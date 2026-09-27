import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import { notifyMacContactsSettingsReady, onMacContactsSettingsEvent, updateMacContactsEnabled } from '../services/macContactsBridge'
import type { MacContactsSettingsFields } from '../types'

function statusMessage(fields: MacContactsSettingsFields): string {
  if (!fields.available) return fields.detail ?? 'Mac Contacts are unavailable to Basil.'
  if (fields.preferenceEnabled && fields.canLookup) return 'Contacts access is enabled for personalized generation.'
  if (fields.authorizationStatus === 'denied' || fields.authorizationStatus === 'restricted') {
    return 'Contacts access is blocked. Open System Settings → Privacy & Security → Contacts to allow Basil.'
  }
  if (fields.authorizationStatus === 'not_determined') return 'Contacts access has not been requested yet.'
  return fields.detail ?? 'Contacts access is currently unavailable.'
}

export function MacContactsSettingsCard() {
  const [fields, setFields] = useState<MacContactsSettingsFields | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null)
  const pendingRequestIdRef = useRef<string | null>(null)
  pendingRequestIdRef.current = pendingRequestId

  useEffect(() => {
    const unsubscribe = onMacContactsSettingsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setFields(event.fields)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.requestId === pendingRequestIdRef.current) {
        pendingRequestIdRef.current = null
        setPendingRequestId(null)
        setRequestError(event.status === 'error' ? event.message ?? 'Unable to update Contacts access.' : null)
      }
    })
    notifyMacContactsSettingsReady()
    return unsubscribe
  }, [])

  function handleChange(enabled: boolean) {
    if (!fields || pendingRequestIdRef.current) return
    setRequestError(null)
    const requestId = updateMacContactsEnabled(enabled)
    pendingRequestIdRef.current = requestId
    setPendingRequestId(requestId)
  }

  return (
    <section className="profile-settings-section mac-contacts-settings-card" aria-labelledby="mac-contacts-settings-heading">
      <h2 id="mac-contacts-settings-heading">Contacts for Personalization</h2>
      <p className="mac-contacts-settings-description">Allow Basil to use local contact identity details to personalize email-related output. Contacts stay on this Mac.</p>
      {loadError ? (
        <>
          <p className="mac-contacts-settings-error" role="alert">{loadError}</p>
          <button type="button" className="secondary-button" onClick={notifyMacContactsSettingsReady}>Retry</button>
        </>
      ) : !fields ? (
        <p className="mac-contacts-settings-status" role="status">Loading Contacts access...</p>
      ) : (
        <>
          <Switch
            id="mac-contacts-enabled"
            label="Allow Contacts lookup for generation"
            checked={fields.preferenceEnabled}
            disabled={pendingRequestId !== null || !fields.available}
            onChange={handleChange}
          />
          <p className={fields.preferenceEnabled && fields.canLookup ? 'mac-contacts-settings-status mac-contacts-settings-status-enabled' : 'mac-contacts-settings-status'} role="status">
            {statusMessage(fields)}
          </p>
          {requestError && <p className="mac-contacts-settings-error" role="alert">{requestError}</p>}
        </>
      )}
    </section>
  )
}
