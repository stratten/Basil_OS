import { useState } from 'react';
import type { ExecutionApprovalRequest } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { hydrateActiveFollowUpChild, hydrateAgentFromBackend } from '../app/agentHydration';
import BrowserSensitiveApprovalDetails from './approval/BrowserSensitiveApprovalDetails';

interface Props {
  agentTaskId: string;
  approval: ExecutionApprovalRequest;
  rememberChoice: boolean;
  embedded?: boolean;
}

export default function ApprovalOverlay({ agentTaskId, approval, rememberChoice, embedded = false }: Props) {
  const [remember, setRemember] = useState(rememberChoice);
  const [submitting, setSubmitting] = useState(false);
  const [commandExpanded, setCommandExpanded] = useState(false);
  const [scriptExpanded, setScriptExpanded] = useState(false);
  const [sensitiveValue, setSensitiveValue] = useState('');

  const isAppleScript = approval.execution_type === 'applescript';
  const isBrowserSensitiveFill = approval.execution_type === 'browser_sensitive_fill';
  const isProviderPermission = approval.execution_type === 'provider_permission';
  const permissionSubject = approval.provider_permission?.subject;
  const providerCommand = typeof permissionSubject?.command === 'string'
    ? permissionSubject.command
    : undefined;
  const commandText = providerCommand || approval.command || '';
  const isLong = commandText.length > 200;
  const needsUserEntry = approval.browser_metadata?.value_source === 'user_entry';
  const scriptContent = approval.script_content;
  const scriptLineCount = scriptContent ? scriptContent.split('\n').length : 0;
  const canApprove = !isProviderPermission || Boolean(approval.provider_permission?.allow_option_id);
  // Only the plain shell-command case's title ("Command Approval Required")
  // is a literal repeat of the aggregate header multi-approval callers
  // already show above every embedded item. The other types (AppleScript,
  // browser-sensitive fill, provider permission) each carry their own
  // differentiating title, so keep those regardless of embedding.
  const suppressTitle = embedded && !isAppleScript && !isBrowserSensitiveFill && !isProviderPermission;

  const handleDecision = async (approved: boolean) => {
    setSubmitting(true);
    try {
      if (isProviderPermission) {
        const permission = approval.provider_permission;
        if (!permission) {
          throw new Error('Provider permission approval is missing its interaction metadata');
        }
        const selectedOptionId = approved ? permission.allow_option_id : permission.reject_option_id;
        if (!selectedOptionId) {
          throw new Error('Provider permission approval has no option to select');
        }
        await api.submitProviderPermissionDecision({
          agent_task_id: permission.agent_task_id,
          interaction_id: permission.interaction_id,
          selected_option_id: selectedOptionId,
        });
      } else if (isBrowserSensitiveFill) {
        await api.submitBrowserSensitiveFillApproval({
          approval_id: approval.approval_id,
          approved,
          remember_domain: remember,
          sensitive_value: approved && needsUserEntry ? sensitiveValue : undefined,
        });
      } else {
        await api.submitApprovalDecision({
          approval_id: approval.approval_id,
          command: approval.command,
          approved,
          remember_choice: remember,
          pattern_type: 'exact',
          agent_task_id: approval.agent_task_id,
          expected_revision: approval.revision,
        });
      }
      agentStore.removeApproval(agentTaskId, approval.approval_id);
      agentStore.updateProgressStep(
        agentTaskId,
        approved ? 'Approval granted, continuing...' : 'Approval denied, continuing...',
        true,
        false,
      );
    } catch (err) {
      console.error('[Approval] Decision failed:', err);
      if (err instanceof Error && /409|conflict|stale/i.test(err.message)) {
        if (
          approval.agent_task_id !== agentTaskId
          && agentStore.getActiveFollowUpId(agentTaskId) === approval.agent_task_id
        ) {
          void hydrateActiveFollowUpChild(agentTaskId, approval.agent_task_id);
        } else {
          hydrateAgentFromBackend(agentTaskId);
        }
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (!isProviderPermission) {
      await handleDecision(false);
      return;
    }

    setSubmitting(true);
    try {
      const permission = approval.provider_permission;
      if (!permission) {
        throw new Error('Provider permission approval is missing its interaction metadata');
      }
      await api.submitProviderPermissionDecision({
        agent_task_id: permission.agent_task_id,
        interaction_id: permission.interaction_id,
        outcome: 'cancel',
      });
      agentStore.removeApproval(agentTaskId, approval.approval_id);
      agentStore.updateProgressStep(agentTaskId, 'Permission canceled, continuing...', true, false);
    } catch (err) {
      console.error('[Approval] Provider permission cancellation failed:', err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={embedded ? 'approval-set-card' : 'overlay-backdrop'}>
      <div
        className="overlay-card"
        data-agent-desk-interactive-overlay="true"
        data-preferred-content-width={scriptContent ? 640 : 480}
        style={{ maxWidth: `clamp(360px, 60vw, ${scriptContent ? 640 : 480}px)` }}
      >
        {!suppressTitle && (
          <div className="overlay-title">
            {isProviderPermission
              ? 'Provider Permission Request'
              : isBrowserSensitiveFill
                ? 'Sensitive Browser Fill Approval'
                : isAppleScript
                  ? 'AppleScript Approval Required'
                  : 'Command Approval Required'}
          </div>
        )}

        <div className="overlay-body">
          {/* Risk level */}
          <div className="approval-section">
            <span className={`risk-badge ${approval.risk_level}`}>
              {approval.risk_level} risk
            </span>
            {isAppleScript && (
              <span className="approval-tag">
                AppleScript
              </span>
            )}
            {isBrowserSensitiveFill && (
              <span className="approval-tag">
                Browser
              </span>
            )}
            {isProviderPermission && (
              <span className="approval-tag">
                Provider
              </span>
            )}
          </div>

          {isBrowserSensitiveFill && (
            <BrowserSensitiveApprovalDetails metadata={approval.browser_metadata} />
          )}

          {/* Agent task text */}
          <div className="approval-section">
            <div
              className={!commandExpanded && isLong ? 'command-display command-display--collapsed' : 'command-display'}
            >
              {commandText}
            </div>
            {isLong && (
              <button
                className="approval-link-button"
                onClick={() => setCommandExpanded(!commandExpanded)}
              >
                {commandExpanded ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>

          {/* Expandable script preview */}
          {scriptContent && (
            <div className="approval-section">
              <button
                className="approval-link-button approval-link-button--toggle"
                onClick={() => setScriptExpanded(!scriptExpanded)}
              >
                <span className={scriptExpanded ? 'approval-link-button__arrow approval-link-button__arrow--open' : 'approval-link-button__arrow'}>&#9654;</span>
                {`View full script (${scriptLineCount} lines)`}
              </button>
              {scriptExpanded && (
                <div
                  className="command-display approval-script-preview"
                >
                  {scriptContent}
                </div>
              )}
            </div>
          )}

          {isBrowserSensitiveFill && needsUserEntry && (
            <div className="approval-section">
              <label className="approval-field-label">
                Sensitive value
              </label>
              <input
                className="approval-sensitive-input"
                type="password"
                value={sensitiveValue}
                onChange={e => setSensitiveValue(e.target.value)}
                autoComplete="off"
              />
            </div>
          )}

          {/* Reason */}
          <p className="approval-reason">
            {approval.reason}
          </p>

          {/* Pattern */}
          {approval.generalized_pattern && (
            <p className="approval-pattern">
              Pattern: {approval.generalized_pattern}
            </p>
          )}

          {/* Risk warning */}
          {approval.risk_level === 'high' && (
            <div className="approval-high-risk-notice">
              This command may cause permanent changes
            </div>
          )}

          {/* Remember choice */}
          {!isProviderPermission && (
            <label className="checkbox-row approval-remember">
              <input
                type="checkbox"
                checked={remember}
                onChange={e => setRemember(e.target.checked)}
                disabled={isBrowserSensitiveFill && !approval.browser_metadata?.will_remember_domain_allowed}
              />
              {isBrowserSensitiveFill ? 'Remember this domain' : 'Remember this choice'}
            </label>
          )}
        </div>

        <div className="overlay-actions">
          <button className="action-btn" onClick={handleCancel} disabled={submitting}>
            Cancel
          </button>
          <button
            className="action-btn danger"
            onClick={() => handleDecision(false)}
            disabled={submitting}
          >
            Deny
          </button>
          <button
            className="action-btn success"
            onClick={() => handleDecision(true)}
            disabled={submitting || !canApprove}
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
