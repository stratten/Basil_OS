import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import PresenceRegion from '@shared/PresenceRegion'
import type { ApprovalMode, ApprovalTimeoutBehavior, WhitelistPatternFields } from '../types'
import {
  notifyPermissionsCommandSecurityReady,
  onPermissionsCommandSecurityEvent,
  requestAddWhitelistPattern,
  requestDeleteWhitelistPattern,
  requestUpdateApprovalSetting,
  requestUpdateWhitelistPattern,
} from '../services/permissionsCommandSecurityBridge'
import { WhitelistPatternForm } from './WhitelistPatternForm'

const APPROVAL_MODE_OPTIONS: readonly { id: ApprovalMode; label: string }[] = [
  { id: 'always_approve', label: 'Always Approve (Risky)' },
  { id: 'whitelist_only', label: 'Whitelist Only (Recommended)' },
  { id: 'always_prompt', label: 'Always Prompt (Safest)' },
]

const TIMEOUT_BEHAVIOR_OPTIONS: readonly { id: ApprovalTimeoutBehavior; label: string }[] = [
  { id: 'wait_forever', label: 'Always wait for my response' },
  { id: 'deny_on_timeout', label: 'Deny after timeout' },
  { id: 'retry_alternative', label: 'Deny after timeout and attempt alternative' },
]

type PendingAction = 'approval-setting' | 'add-pattern' | 'update-pattern' | 'delete-pattern'

export function PermissionsCommandSecurityPanel() {
  const [isLoading, setIsLoading] = useState(true)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [approvalMode, setApprovalMode] = useState<ApprovalMode>('whitelist_only')
  const [safeExecutionMode, setSafeExecutionMode] = useState(false)
  const [autoApproveReadOnly, setAutoApproveReadOnly] = useState(false)
  const [blockDangerousPatterns, setBlockDangerousPatterns] = useState(false)
  const [approvalTimeoutSeconds, setApprovalTimeoutSeconds] = useState(120)
  const [timeoutBehavior, setTimeoutBehavior] = useState<ApprovalTimeoutBehavior>('wait_forever')
  const [whitelistPatterns, setWhitelistPatterns] = useState<WhitelistPatternFields[]>([])
  const [showPatternForm, setShowPatternForm] = useState(false)
  const [editingPattern, setEditingPattern] = useState<WhitelistPatternFields | null>(null)
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const pendingActionRef = useRef<{ requestId: string; action: PendingAction } | null>(null)

  useEffect(() => {
    const unsubscribe = onPermissionsCommandSecurityEvent((event) => {
      if (event.type === 'loadError') {
        setLoadError(event.message)
        setIsLoading(false)
        return
      }
      if (event.type === 'init' || event.type === 'snapshot') {
        setIsLoading(event.isLoading)
        if (!event.isLoading) setHasLoaded(true)
        setLoadError(event.error)
        if (event.approvalSettings) {
          setApprovalMode(event.approvalSettings.approvalMode)
          setSafeExecutionMode(event.approvalSettings.safeExecutionMode)
          setAutoApproveReadOnly(event.approvalSettings.autoApproveReadOnly)
          setBlockDangerousPatterns(event.approvalSettings.blockDangerousPatterns)
          setApprovalTimeoutSeconds(event.approvalSettings.approvalTimeoutSeconds)
          setTimeoutBehavior(event.approvalSettings.timeoutBehavior)
        }
        setWhitelistPatterns(event.whitelistPatterns)
        return
      }
      if (event.type !== 'intentResult' || event.requestId !== pendingActionRef.current?.requestId) return
      const pendingAction = pendingActionRef.current.action
      pendingActionRef.current = null
      setPendingRequestId(null)
      setRequestError(event.status === 'error' ? event.message ?? 'The update did not complete.' : null)
      if (event.status === 'success' && (pendingAction === 'add-pattern' || pendingAction === 'update-pattern')) {
        setShowPatternForm(false)
        setEditingPattern(null)
      }
    })
    notifyPermissionsCommandSecurityReady()
    return unsubscribe
  }, [])

  function openAddPatternForm() {
    setEditingPattern(null)
    setShowPatternForm(true)
  }

  function openEditPatternForm(pattern: WhitelistPatternFields) {
    setEditingPattern(pattern)
    setShowPatternForm(true)
  }

  function closePatternForm() {
    setShowPatternForm(false)
    setEditingPattern(null)
  }

  function startRequest(action: PendingAction, requestId: string) {
    pendingActionRef.current = { action, requestId }
    setPendingRequestId(requestId)
    setRequestError(null)
  }

  function requestApprovalSetting(patch: Parameters<typeof requestUpdateApprovalSetting>[0]) {
    startRequest('approval-setting', requestUpdateApprovalSetting(patch))
  }

  function handleSubmitPattern(pattern: string, patternType: string, description: string) {
    if (editingPattern) {
      startRequest('update-pattern', requestUpdateWhitelistPattern(editingPattern.id, pattern, patternType, description))
    } else {
      startRequest('add-pattern', requestAddWhitelistPattern(pattern, patternType, description))
    }
  }

  if (isLoading && !hasLoaded) {
    return <div className="permissions-command-security-panel">Loading command approval settings…</div>
  }

  if (loadError) {
    return (
      <div className="permissions-command-security-panel">
        <p className="permissions-whitelist-form-error">{loadError}</p>
        <button type="button" className="permissions-application-refresh" onClick={notifyPermissionsCommandSecurityReady}>
          Retry
        </button>
      </div>
    )
  }

  return (
    <section className="permissions-command-security-panel">
      <header className="permissions-command-security-header">
        <div>
          <h2>Command Execution Security</h2>
          <p>Control how shell commands and AppleScript from agent tasks are approved before execution.</p>
        </div>
      </header>
      {requestError && <p className="permissions-whitelist-form-error" role="alert">{requestError}</p>}

      <div className="permissions-command-security-section">
        <h3 className="permissions-command-security-section-title">Safe Execution Mode</h3>
        <p className="permissions-command-security-section-description">
          Require explicit approval for ALL script and command execution, regardless of other settings.
        </p>
        <Switch
          id="permissions-safe-execution-mode"
          label="Enable Safe Execution Mode"
          checked={safeExecutionMode}
          disabled={pendingRequestId !== null}
          onChange={(checked) => requestApprovalSetting({ safeExecutionMode: checked })}
        />
      </div>

      <div className="permissions-command-security-pair">
        <div className="permissions-command-security-section">
          <h3 className="permissions-command-security-section-title">Approval Timeout</h3>
          <div className="permissions-radio-group">
            {TIMEOUT_BEHAVIOR_OPTIONS.map((option) => (
              <label key={option.id} className="permissions-radio-option">
                <input
                  type="radio"
                  name="timeoutBehavior"
                  checked={timeoutBehavior === option.id}
                  disabled={pendingRequestId !== null}
                  onChange={() => requestApprovalSetting({ timeoutBehavior: option.id })}
                />
                {option.label}
              </label>
            ))}
          </div>
          {timeoutBehavior !== 'wait_forever' && (
            <div className="permissions-timeout-stepper">
              <span className="permissions-toggle-row-label">Timeout after:</span>
              <input
                type="number"
                min={30}
                max={600}
                step={30}
                value={approvalTimeoutSeconds}
                disabled={pendingRequestId !== null}
                onChange={(event) => {
                  const seconds = Number(event.target.value)
                  if (Number.isInteger(seconds)) requestApprovalSetting({ approvalTimeoutSeconds: seconds })
                }}
              />
              <span className="permissions-toggle-row-label">seconds</span>
            </div>
          )}
        </div>

        <div className="permissions-command-security-section" style={safeExecutionMode ? { opacity: 0.5 } : undefined}>
          <h3 className="permissions-command-security-section-title">Approval Mode</h3>
          {safeExecutionMode && <p className="permissions-command-security-section-description">Superseded by Safe Execution Mode.</p>}
          <div className="permissions-radio-group">
            {APPROVAL_MODE_OPTIONS.map((option) => (
              <label key={option.id} className="permissions-radio-option">
                <input
                  type="radio"
                  name="approvalMode"
                  disabled={safeExecutionMode || pendingRequestId !== null}
                  checked={approvalMode === option.id}
                  onChange={() => requestApprovalSetting({ approvalMode: option.id })}
                />
                {option.label}
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="permissions-command-security-section" style={safeExecutionMode ? { opacity: 0.5 } : undefined}>
        <h3 className="permissions-command-security-section-title">Security Options</h3>
        <div className="permissions-command-security-switch-stack">
          <Switch
            id="permissions-auto-approve-read-only"
            label="Auto-approve read-only commands (ls, cat, grep, etc.)"
            checked={autoApproveReadOnly}
            disabled={safeExecutionMode || pendingRequestId !== null}
            onChange={(checked) => requestApprovalSetting({ autoApproveReadOnly: checked })}
          />
          <Switch
            id="permissions-block-dangerous-patterns"
            label="Block dangerous patterns (rm -rf /, sudo rm, etc.)"
            checked={blockDangerousPatterns}
            disabled={pendingRequestId !== null}
            onChange={(checked) => requestApprovalSetting({ blockDangerousPatterns: checked })}
          />
        </div>
      </div>

      <div className="permissions-command-security-section">
        <div className="permissions-whitelist-header">
          <h3 className="permissions-command-security-section-title">Whitelisted Commands ({whitelistPatterns.length})</h3>
          <button type="button" className="permissions-whitelist-add-button" disabled={pendingRequestId !== null} onClick={openAddPatternForm}>
            + Add Pattern
          </button>
        </div>

        <PresenceRegion visible={showPatternForm && editingPattern === null} className="basil-presence" settleWithoutTransition>
          <WhitelistPatternForm editingPattern={null} disabled={pendingRequestId !== null} onSubmit={handleSubmitPattern} onCancel={closePatternForm} />
        </PresenceRegion>

        {whitelistPatterns.length === 0 ? (
          <p className="permissions-whitelist-empty">No whitelisted commands yet. Add patterns to allow commands without prompting.</p>
        ) : (
          <div className="permissions-whitelist-table" role="list">
            {whitelistPatterns.map((pattern) => (
              <div key={pattern.id} className="permissions-whitelist-item" role="listitem">
                <article className="permissions-whitelist-row">
                  <div className="permissions-whitelist-details">
                    <div className="permissions-whitelist-pattern-heading">
                      <span className="permissions-whitelist-type">{pattern.patternType}</span>
                      <code className="permissions-whitelist-pattern" title={pattern.pattern}>{pattern.pattern}</code>
                    </div>
                    <span className="permissions-whitelist-description">{pattern.description || 'No description provided'}</span>
                  </div>
                  <span className="permissions-whitelist-use-count">{pattern.useCount} {pattern.useCount === 1 ? 'use' : 'uses'}</span>
                  <div className="permissions-whitelist-actions">
                    <button type="button" className="permissions-whitelist-action-button" disabled={pendingRequestId !== null} onClick={() => openEditPatternForm(pattern)}>
                      Edit
                    </button>
                    <button
                      type="button"
                      className="permissions-whitelist-action-button permissions-whitelist-delete-button"
                      disabled={pendingRequestId !== null}
                      onClick={() => startRequest('delete-pattern', requestDeleteWhitelistPattern(pattern.id))}
                    >
                      Delete
                    </button>
                  </div>
                </article>
                <PresenceRegion visible={showPatternForm && editingPattern?.id === pattern.id} className="basil-presence" settleWithoutTransition>
                  {showPatternForm && editingPattern?.id === pattern.id && (
                    <WhitelistPatternForm editingPattern={editingPattern} disabled={pendingRequestId !== null} onSubmit={handleSubmitPattern} onCancel={closePatternForm} />
                  )}
                </PresenceRegion>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
