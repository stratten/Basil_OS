import { useEffect, useRef, useState } from 'react'
import {
  notifyAccountSettingsReady,
  onAccountEvent,
  requestDeleteAccount,
  requestGoogleSignIn,
  requestLogin,
  requestPaymentSetup,
  requestRefreshPaymentAndUsage,
  requestSetApiKeyPreference,
  requestSignOut,
  requestSignup,
} from '../services/accountBridge'
import type { AccountInitEvent, AccountSettingsFields, AccountSnapshotEvent, ApiKeyPreference } from '../types'
import '../styles/account-settings.css'

const BASIL_CLOUD_ALIASES: readonly ApiKeyPreference[] = ['basil_cloud', 'app_keys', 'trial']

function normalizedPreferenceGroup(preference: ApiKeyPreference): ApiKeyPreference {
  return BASIL_CLOUD_ALIASES.includes(preference) ? 'basil_cloud' : preference
}

function extractFields(event: AccountInitEvent | AccountSnapshotEvent): AccountSettingsFields {
  return {
    isAuthenticated: event.isAuthenticated,
    userEmail: event.userEmail,
    subscriptionStatus: event.subscriptionStatus,
    hasPaymentMethod: event.hasPaymentMethod,
    cardBrand: event.cardBrand,
    cardLast4: event.cardLast4,
    cardExpiration: event.cardExpiration,
    apiKeyPreference: event.apiKeyPreference,
    basilCloudSelected: event.basilCloudSelected,
    basilCloudBadge: event.basilCloudBadge,
    basilCloudDescription: event.basilCloudDescription,
    trialExhausted: event.trialExhausted,
    isLoadingUsage: event.isLoadingUsage,
    currentPeriodFormatted: event.currentPeriodFormatted,
    totalCostFormatted: event.totalCostFormatted,
    totalTokensFormatted: event.totalTokensFormatted,
    usageByModel: event.usageByModel,
  }
}

type AuthMode = 'login' | 'signup'

export function AccountSettingsApp() {
  const [settings, setSettings] = useState<AccountSettingsFields | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const pendingRef = useRef<string | null>(null)
  pendingRef.current = pendingId

  useEffect(() => {
    const unsubscribe = onAccountEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        const fields = extractFields(event)
        setSettings(fields)
        setLoadError(null)
        if (fields.isAuthenticated) {
          setEmail('')
          setPassword('')
          setConfirmPassword('')
        }
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRef.current) {
        setPendingId(null)
        setRequestError(event.status === 'error' ? event.message ?? 'Something went wrong.' : null)
      }
    })
    notifyAccountSettingsReady()
    return unsubscribe
  }, [])

  function submit(id: string) {
    if (pendingRef.current) return
    setRequestError(null)
    setPendingId(id)
  }

  function handleAuthSubmit() {
    if (authMode === 'login') {
      submit(requestLogin(email, password))
    } else {
      submit(requestSignup(email, password, confirmPassword))
    }
  }

  function handleDeleteConfirmed() {
    setShowDeleteConfirm(false)
    submit(requestDeleteAccount())
  }

  if (!settings && !loadError) {
    return <p className="account-settings-status" role="status">Loading account...</p>
  }

  if (loadError) {
    return (
      <div className="account-settings-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyAccountSettingsReady()}>Retry</button>
      </div>
    )
  }

  const s = settings!
  const disabled = pendingId !== null
  const isAuthFormValid = email.length > 0 && password.length > 0 && (authMode === 'login' || (password === confirmPassword && password.length >= 8))
  const selectedGroup = normalizedPreferenceGroup(s.apiKeyPreference)

  return (
    <div className="account-settings">
      <header className="account-settings-header">
        <h2>Account</h2>
        <p>Manage your Basil account, model access, payment method, and usage.</p>
      </header>

      <section className="account-settings-section" aria-labelledby="account-status-heading">
        <h3 id="account-status-heading">Account Status</h3>
        {s.isAuthenticated ? (
          <div className="account-status-row account-status-row-signed-in">
            <div>
              <p className="account-status-label">Signed in as</p>
              <p className="account-status-value">{s.userEmail}</p>
            </div>
            <button type="button" className="secondary-button" disabled={disabled} onClick={() => submit(requestSignOut())}>Sign Out</button>
          </div>
        ) : (
          <div className="account-auth-form">
            <div className="account-auth-tabs">
              <button type="button" className={authMode === 'login' ? 'account-auth-tab account-auth-tab-selected' : 'account-auth-tab'} onClick={() => setAuthMode('login')}>Sign In</button>
              <button type="button" className={authMode === 'signup' ? 'account-auth-tab account-auth-tab-selected' : 'account-auth-tab'} onClick={() => setAuthMode('signup')}>Create Account</button>
            </div>
            <label className="account-auth-field">
              Email
              <input type="email" autoComplete="email" value={email} disabled={disabled} onChange={(event) => setEmail(event.target.value)} />
            </label>
            <label className="account-auth-field">
              Password
              <input type="password" autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} value={password} disabled={disabled} onChange={(event) => setPassword(event.target.value)} />
            </label>
            {authMode === 'signup' && (
              <label className="account-auth-field">
                Confirm Password
                <input type="password" autoComplete="new-password" value={confirmPassword} disabled={disabled} onChange={(event) => setConfirmPassword(event.target.value)} />
              </label>
            )}
            <div className="account-auth-actions">
              <button type="button" className="primary-button" disabled={disabled || !isAuthFormValid} onClick={handleAuthSubmit}>
                {authMode === 'login' ? 'Sign In' : 'Create Account'}
              </button>
              <button type="button" className="secondary-button" disabled={disabled} onClick={() => submit(requestGoogleSignIn())}>Continue with Google</button>
            </div>
          </div>
        )}
      </section>

      <section className="account-settings-section" aria-labelledby="account-model-access-heading">
        <h3 id="account-model-access-heading">AI Model Access</h3>
        <p className="account-settings-hint">Choose how Basil connects to AI models.</p>
        <div className="account-preference-list" role="radiogroup" aria-labelledby="account-model-access-heading">
          <label className={selectedGroup === 'basil_cloud' ? 'account-preference-row account-preference-row-selected' : 'account-preference-row'}>
            <input type="radio" name="account-api-key-preference" checked={selectedGroup === 'basil_cloud'} disabled={disabled} onChange={() => submit(requestSetApiKeyPreference('basil_cloud'))} />
            <div className="account-preference-row-body">
              <span className="account-preference-row-title">
                Use Basil Cloud
                <span className="account-preference-badge">{s.basilCloudBadge}</span>
              </span>
              <span className="account-preference-row-description">{s.basilCloudDescription}</span>
            </div>
          </label>
          <label className={selectedGroup === 'own_keys' ? 'account-preference-row account-preference-row-selected' : 'account-preference-row'}>
            <input type="radio" name="account-api-key-preference" checked={selectedGroup === 'own_keys'} disabled={disabled} onChange={() => submit(requestSetApiKeyPreference('own_keys'))} />
            <div className="account-preference-row-body">
              <span className="account-preference-row-title">Use Your Own Provider Account</span>
              <span className="account-preference-row-description">Connect directly with your own API keys. Basil does not bill model usage.</span>
            </div>
          </label>
          <label className={selectedGroup === 'local' ? 'account-preference-row account-preference-row-selected' : 'account-preference-row'}>
            <input type="radio" name="account-api-key-preference" checked={selectedGroup === 'local'} disabled={disabled} onChange={() => submit(requestSetApiKeyPreference('local'))} />
            <div className="account-preference-row-body">
              <span className="account-preference-row-title">Local Models Only</span>
              <span className="account-preference-row-description">Use on-device models only. Limited capabilities, no cloud requests.</span>
            </div>
          </label>
        </div>
      </section>

      {s.isAuthenticated && (
        <>
          <section className="account-settings-section" aria-labelledby="account-payment-heading">
            <h3 id="account-payment-heading">Payment Method</h3>
            {s.hasPaymentMethod ? (
              <div className="account-status-row">
                <div>
                  <p className="account-status-value">{s.cardBrand} ending in {s.cardLast4}</p>
                  <p className="account-status-label">Expires {s.cardExpiration}</p>
                </div>
                <button type="button" className="secondary-button" disabled={disabled} onClick={() => submit(requestPaymentSetup())}>Update</button>
              </div>
            ) : (
              <div className="account-status-row account-status-row-warning">
                <div>
                  <p className="account-status-value">No payment method</p>
                  <p className="account-status-label">Add a payment method to use cloud AI models</p>
                </div>
                <button type="button" className="primary-button" disabled={disabled} onClick={() => submit(requestPaymentSetup())}>Add Payment Method</button>
              </div>
            )}
            <button type="button" className="account-refresh-link" disabled={disabled} onClick={() => submit(requestRefreshPaymentAndUsage())}>Refresh status</button>
          </section>

          <section className="account-settings-section" aria-labelledby="account-usage-heading">
            <h3 id="account-usage-heading">Current Usage</h3>
            <p className="account-status-label">This Month ({s.currentPeriodFormatted})</p>
            <div className="account-usage-totals">
              <div>
                <p className="account-status-label">Total Cost</p>
                <p className="account-usage-total-value">{s.totalCostFormatted}</p>
              </div>
              <div>
                <p className="account-status-label">Tokens Used</p>
                <p className="account-usage-total-value">{s.totalTokensFormatted}</p>
              </div>
            </div>
            {s.usageByModel.length > 0 && (
              <ul className="account-usage-by-model">
                {s.usageByModel.map((entry) => (
                  <li key={entry.model}>
                    <span>{entry.model}</span>
                    <span>${entry.costUsd.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="account-settings-section account-danger-zone" aria-labelledby="account-danger-heading">
            <h3 id="account-danger-heading">Danger Zone</h3>
            <div className="account-status-row">
              <div>
                <p className="account-status-value">Delete Account</p>
                <p className="account-status-label">Permanently delete your account and all data</p>
              </div>
              <button type="button" className="account-delete-button" disabled={disabled} onClick={() => setShowDeleteConfirm((current) => !current)}>Delete Account</button>
            </div>
            {showDeleteConfirm && (
              <div className="account-delete-confirm" role="group" aria-label="Delete account?">
                <p className="account-delete-confirm-title">Delete your account?</p>
                <p className="account-delete-confirm-body">This action cannot be undone. All your data will be permanently deleted.</p>
                <div className="account-delete-confirm-actions">
                  <button type="button" className="secondary-button" onClick={() => setShowDeleteConfirm(false)}>Cancel</button>
                  <button type="button" className="account-delete-confirm-button" disabled={disabled} onClick={handleDeleteConfirmed}>Delete</button>
                </div>
              </div>
            )}
          </section>
        </>
      )}

      {pendingId && <p className="account-settings-status" role="status">Saving...</p>}
      {requestError && <p className="account-settings-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
