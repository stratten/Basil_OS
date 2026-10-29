import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import {
  requestAccountGoogleSignIn,
  requestAccountLogin,
  requestAccountPaymentSetup,
  requestAccountRefresh,
  requestAccountSignup,
} from '@/services/bridge'
import type { SetupAgentModelAccessOption } from '@/types'

export const ACCOUNT_POLL_INTERVAL_MS = 3000
export const ACCOUNT_POLL_LIMIT_MS = 5 * 60 * 1000
export const MINIMUM_PASSWORD_LENGTH = 8

type AccountFormMode = 'signIn' | 'signUp'
type WaitingFor = 'google' | 'payment' | null

interface Props {
  option: SetupAgentModelAccessOption
  /** Re-reads the model-access options so the Basil Cloud row reflects the account's new state. */
  refreshOptions: () => Promise<void>
}

export function validateAccountForm(
  mode: AccountFormMode,
  email: string,
  password: string,
  confirmPassword: string,
): string | null {
  const trimmedEmail = email.trim()
  if (!trimmedEmail || !trimmedEmail.includes('@')) return 'Enter the email address for your Basil account.'
  if (!password) return 'Enter your password.'
  if (mode === 'signUp') {
    if (password.length < MINIMUM_PASSWORD_LENGTH) {
      return `Password must be at least ${MINIMUM_PASSWORD_LENGTH} characters.`
    }
    if (password !== confirmPassword) return 'Passwords don’t match.'
  }
  return null
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

/**
 * Lets someone sign in, create an account, and add a payment method for Basil Cloud without leaving setup.
 * Password sign-in and sign-up complete in the app; Google sign-in and the Stripe payment page complete in the browser, so the panel watches the account until it becomes eligible.
 */
export function BasilCloudAccountPanel({ option, refreshOptions }: Props) {
  const [mode, setMode] = useState<AccountFormMode>('signIn')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isBusy, setIsBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [waitingFor, setWaitingFor] = useState<WaitingFor>(null)
  const [pollTimedOut, setPollTimedOut] = useState(false)
  const isMountedRef = useRef(true)
  const refreshOptionsRef = useRef(refreshOptions)
  refreshOptionsRef.current = refreshOptions

  const needsSignIn = Boolean(option.requires_sign_in)
  const needsPayment = !needsSignIn && Boolean(option.requires_payment_method)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  // Waits for the browser half of Google sign-in or the Stripe page by re-reading the account, never by guessing a delay.
  useEffect(() => {
    if (!waitingFor) return undefined
    let isCurrent = true
    const startedAt = Date.now()
    const poll = async () => {
      while (isCurrent) {
        await new Promise<void>(resolve => window.setTimeout(resolve, ACCOUNT_POLL_INTERVAL_MS))
        if (!isCurrent) return
        if (Date.now() - startedAt > ACCOUNT_POLL_LIMIT_MS) {
          setWaitingFor(null)
          setPollTimedOut(true)
          return
        }
        try {
          if (waitingFor === 'payment') await requestAccountRefresh()
          await refreshOptionsRef.current()
        } catch {
          // A failed check is retried on the next tick; the manual button reports errors.
        }
      }
    }
    void poll()
    return () => {
      isCurrent = false
    }
  }, [waitingFor])

  const resetMessages = () => {
    setErrorMessage(null)
    setStatusMessage(null)
    setPollTimedOut(false)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (isBusy) return
    resetMessages()
    const validationError = validateAccountForm(mode, email, password, confirmPassword)
    if (validationError) {
      setErrorMessage(validationError)
      return
    }
    setIsBusy(true)
    try {
      if (mode === 'signIn') {
        await requestAccountLogin(email.trim(), password)
      } else {
        await requestAccountSignup(email.trim(), password, confirmPassword)
      }
      setPassword('')
      setConfirmPassword('')
      await refreshOptionsRef.current()
    } catch (error) {
      if (isMountedRef.current) {
        setErrorMessage(errorText(error, mode === 'signIn' ? 'I couldn’t sign you in.' : 'I couldn’t create that account.'))
      }
    } finally {
      if (isMountedRef.current) setIsBusy(false)
    }
  }

  const continueWithGoogle = async () => {
    if (isBusy) return
    resetMessages()
    setIsBusy(true)
    try {
      const result = await requestAccountGoogleSignIn()
      setStatusMessage(result.message || 'Finish signing in with Google in your browser, then come back here.')
      setWaitingFor('google')
    } catch (error) {
      setErrorMessage(errorText(error, 'I couldn’t start Google sign-in.'))
    } finally {
      if (isMountedRef.current) setIsBusy(false)
    }
  }

  const addPaymentMethod = async () => {
    if (isBusy) return
    resetMessages()
    setIsBusy(true)
    try {
      await requestAccountPaymentSetup()
      setStatusMessage('Finish adding your card on the Stripe page in your browser, then come back here.')
      setWaitingFor('payment')
    } catch (error) {
      setErrorMessage(errorText(error, 'I couldn’t open the payment page.'))
    } finally {
      if (isMountedRef.current) setIsBusy(false)
    }
  }

  const checkAgain = async () => {
    if (isBusy) return
    resetMessages()
    setIsBusy(true)
    try {
      await requestAccountRefresh().catch(() => undefined)
      await refreshOptionsRef.current()
      if (isMountedRef.current) {
        setStatusMessage('Not ready yet. I’ll keep checking while you finish in your browser.')
        setWaitingFor(current => current ?? (needsPayment ? 'payment' : 'google'))
      }
    } catch (error) {
      if (isMountedRef.current) setErrorMessage(errorText(error, 'I couldn’t check your account.'))
    } finally {
      if (isMountedRef.current) setIsBusy(false)
    }
  }

  if (!needsSignIn && !needsPayment) return null

  return (
    <div className="choice-option-reveal-body basil-cloud-account" data-testid="basil-cloud-account-panel">
      {needsSignIn && (
        <>
          <div className="basil-cloud-account-tabs" role="group" aria-label="Basil account">
            <button
              type="button"
              className="basil-cloud-account-tab"
              aria-pressed={mode === 'signIn'}
              disabled={isBusy}
              onClick={() => { setMode('signIn'); resetMessages() }}
            >
              Sign in
            </button>
            <button
              type="button"
              className="basil-cloud-account-tab"
              aria-pressed={mode === 'signUp'}
              disabled={isBusy}
              onClick={() => { setMode('signUp'); resetMessages() }}
            >
              Create account
            </button>
          </div>
          <form className="basil-cloud-account-form" onSubmit={event => void submit(event)}>
            <label>
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={event => setEmail(event.target.value)}
                autoComplete="email"
                disabled={isBusy}
              />
            </label>
            <label>
              <span>Password</span>
              <input
                type="password"
                value={password}
                onChange={event => setPassword(event.target.value)}
                autoComplete={mode === 'signIn' ? 'current-password' : 'new-password'}
                disabled={isBusy}
              />
            </label>
            {mode === 'signUp' && (
              <label>
                <span>Confirm password</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={event => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                  disabled={isBusy}
                />
              </label>
            )}
            <div className="basil-cloud-account-actions">
              <button type="submit" className="secondary-button" disabled={isBusy}>
                {isBusy ? 'Working…' : mode === 'signIn' ? 'Sign in' : 'Create account'}
              </button>
              <button type="button" className="secondary-button" disabled={isBusy} onClick={() => void continueWithGoogle()}>
                Continue with Google
              </button>
            </div>
          </form>
          {mode === 'signUp' && (
            <p className="choice-option-note">
              After you create your account, you’ll add a payment method on a secure Stripe page in your browser. Basil never sees your card.
            </p>
          )}
        </>
      )}
      {needsPayment && (
        <div className="basil-cloud-account-payment">
          <p className="choice-option-note">
            You’re signed in. Basil Cloud bills usage to a card, so add a payment method on a secure Stripe page in your browser. Basil never sees your card.
          </p>
          <div className="basil-cloud-account-actions">
            <button type="button" className="secondary-button" disabled={isBusy} onClick={() => void addPaymentMethod()}>
              Add payment method
            </button>
            <button type="button" className="secondary-button" disabled={isBusy} onClick={() => void checkAgain()}>
              I’ve added it
            </button>
          </div>
        </div>
      )}
      {waitingFor && (
        <p className="choice-option-note" role="status">
          {statusMessage ?? 'Waiting for you to finish in your browser…'}
        </p>
      )}
      {waitingFor === 'google' && (
        <div className="basil-cloud-account-actions">
          <button type="button" className="secondary-button" disabled={isBusy} onClick={() => void checkAgain()}>
            I’ve signed in
          </button>
        </div>
      )}
      {!waitingFor && statusMessage && !errorMessage && (
        <p className="choice-option-note" role="status">{statusMessage}</p>
      )}
      {pollTimedOut && (
        <p className="choice-option-note" role="status">
          I stopped waiting. {needsPayment ? 'Press “I’ve added it”' : 'Press “Continue with Google” again or sign in with your password'} when you’re ready.
        </p>
      )}
      {errorMessage && (
        <p className="choice-option-key-status choice-option-key-status--invalid" role="alert">{errorMessage}</p>
      )}
    </div>
  )
}
