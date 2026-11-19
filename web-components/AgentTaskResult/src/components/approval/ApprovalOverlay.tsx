import { useEffect, useRef, useState } from 'react';
import type { ExecutionApprovalRequest } from '../../types';
import * as api from '../../services/api';
import { agentStore } from '../../store/agentStore';
import { hydrateActiveFollowUpChild, hydrateAgentFromBackend } from '../../app/agents/agentHydration';
import BrowserSensitiveApprovalDetails from './BrowserSensitiveApprovalDetails';
import SettingsChangeApprovalDetails from './SettingsChangeApprovalDetails';
import ApprovalExplanationSection, { approvalCanBeRemembered } from './ApprovalExplanationSection';
import ResponseCountdown from '../interaction/ResponseCountdown';
import { COMMAND_PREVIEW_CHARS, previewCommand } from './commandPreview';
import { ApproveCircleIcon, DenyCircleIcon, StopCircleIcon, ViewWorkCircleIcon } from '@shared/windowChrome/CircleControlIcons';
import { DecisionActions, DecisionButton } from '../interaction/DecisionButton';
import CollapsibleRegion from '@shared/disclosure/CollapsibleRegion';
import ExpandableClamp from '@shared/disclosure/ExpandableClamp';

export { COMMAND_PREVIEW_CHARS, previewCommand };

interface Props {
  agentTaskId: string;
  approval: ExecutionApprovalRequest;
  rememberChoice: boolean;
  embedded?: boolean;
  /** Docks the approval to a slim bar so the work behind it can be seen. Absent where the host cannot dock, such as inside a stack of approvals. */
  onMinimize?: () => void;
  /** Ends the whole task, the same action as the header Stop. Absent where the host cannot stop the task. */
  onStopTask?: () => void;
  isStopping?: boolean;
}

export default function ApprovalOverlay({
  agentTaskId,
  approval,
  rememberChoice,
  embedded = false,
  onMinimize,
  onStopTask,
  isStopping = false,
}: Props) {
  const [remember, setRemember] = useState(rememberChoice);
  const [submitting, setSubmitting] = useState(false);
  const [commandExpanded, setCommandExpanded] = useState(false);
  const [scriptExpanded, setScriptExpanded] = useState(false);
  const [sensitiveValue, setSensitiveValue] = useState('');
  const [note, setNote] = useState('');
  const [noteOpen, setNoteOpen] = useState(false);
  const noteInputRef = useRef<HTMLTextAreaElement>(null);

  // The field stays mounted while collapsed, and a collapsed region is still invisible when this effect first runs (a hidden field cannot take focus), so focus waits one frame for it to become visible.
  useEffect(() => {
    if (!noteOpen) return undefined;
    const frame = requestAnimationFrame(() => noteInputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [noteOpen]);

  const isAppleScript = approval.execution_type === 'applescript';
  const isBrowserSensitiveFill = approval.execution_type === 'browser_sensitive_fill';
  const isProviderPermission = approval.execution_type === 'provider_permission';
  const isSettingsChange = approval.execution_type === 'settings_change';
  const showSettingsDiff = isSettingsChange && Boolean(approval.settings_change?.changes.length);
  const permissionSubject = approval.provider_permission?.subject;
  const providerCommand = typeof permissionSubject?.command === 'string'
    ? permissionSubject.command
    : undefined;
  const commandText = providerCommand || approval.command || '';
  const { previewable: isLong } = previewCommand(commandText);
  const needsUserEntry = approval.browser_metadata?.value_source === 'user_entry';
  const scriptContent = approval.script_content;
  const scriptLineCount = scriptContent ? scriptContent.split('\n').length : 0;
  const rememberAllowed = approvalCanBeRemembered(approval);
  // The note rides on the shell and AppleScript decision endpoint. Provider permissions and sensitive browser fills answer through different endpoints that have no place for one.
  const noteAllowed = !isProviderPermission && !isBrowserSensitiveFill && !isSettingsChange;
  const rememberedPattern = approval.whitelist?.pattern;
  // A connected-tool approval is remembered as that one tool's policy, so it shows no command pattern.
  const toolPolicy = approval.whitelist?.tool_policy;
  const showWideCard = Boolean(scriptContent || approval.script_notice);
  const canApprove = !isProviderPermission || Boolean(approval.provider_permission?.allow_option_id);
  // Only the plain shell-command case's title ("Command Approval Required")
  // is a literal repeat of the aggregate header multi-approval callers
  // already show above every embedded item. The other types (AppleScript,
  // browser-sensitive fill, provider permission) each carry their own
  // differentiating title, so keep those regardless of embedding.
  const suppressTitle = embedded && !isAppleScript && !isBrowserSensitiveFill && !isProviderPermission && !isSettingsChange;

  const riskBadge = (
    <span className={`risk-badge ${approval.risk_level}`}>
      {approval.risk_level} risk
    </span>
  );
  const typeTag = isAppleScript
    ? 'AppleScript'
    : isBrowserSensitiveFill
      ? 'Browser'
      : isProviderPermission
        ? 'Provider'
        : isSettingsChange
          ? 'Settings'
          : null;

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
      } else if (isSettingsChange) {
        await api.submitSettingsChangeApproval({
          approval_id: approval.approval_id,
          approved,
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
          remember_choice: remember && rememberAllowed,
          pattern_type: 'exact',
          agent_task_id: approval.agent_task_id,
          expected_revision: approval.revision,
          user_note: noteAllowed && note.trim() ? note.trim() : undefined,
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

  return (
    <div className={embedded ? 'approval-set-card' : 'overlay-backdrop'}>
      <div
        className="overlay-card"
        data-agent-desk-interactive-overlay="true"
        data-preferred-content-width={showWideCard ? 640 : 480}
        style={{ maxWidth: `clamp(360px, 60vw, ${showWideCard ? 640 : 480}px)` }}
      >
        {!suppressTitle && (
          <div className="overlay-title overlay-title--with-badge">
            <span className="overlay-title__text">
              {isProviderPermission
                ? 'Provider Permission Request'
                : isSettingsChange
                  ? 'Settings Change Approval Required'
                  : isBrowserSensitiveFill
                  ? 'Sensitive Browser Fill Approval'
                  : isAppleScript
                    ? 'AppleScript Approval Required'
                    : 'Command Approval Required'}
            </span>
            {riskBadge}
          </div>
        )}

        <div className="overlay-body">
          {/* The risk badge sits at the right of the title. Only a card without a title (one of a stack) carries it here, and the kind tag has no other home. */}
          {(suppressTitle || typeTag) && (
            <div className="approval-section">
              {suppressTitle && riskBadge}
              {typeTag && <span className="approval-tag">{typeTag}</span>}
            </div>
          )}

          {isSettingsChange && (
            <SettingsChangeApprovalDetails metadata={approval.settings_change} />
          )}

          {isBrowserSensitiveFill && (
            <BrowserSensitiveApprovalDetails metadata={approval.browser_metadata} />
          )}

          {/* The agent's own explanation leads; the command is a short preview behind an expander. */}
          <ApprovalExplanationSection approval={approval} />

          {!showSettingsDiff && (
          <div className="approval-section">
            <div className="command-display approval-command-display">
              {/* The whole command is always present and only clamped to its first line, so opening it is a height animation rather than a swap of two texts. */}
              <ExpandableClamp expanded={commandExpanded || !isLong} collapsedLines={1} className="approval-command-clamp">
                {commandText}
              </ExpandableClamp>
            </div>
            {isLong && (
              <button
                className="approval-link-button"
                aria-expanded={commandExpanded}
                onClick={() => setCommandExpanded(!commandExpanded)}
              >
                {commandExpanded ? 'Hide full command' : 'Show full command'}
              </button>
            )}
          </div>
          )}

          {/* Expandable script preview */}
          {approval.script_path && !scriptContent && (
            <div className="approval-section">
              <div className="approval-script-path">
                <span className="approval-script-path__label">Script file</span>{' '}
                <code>{approval.script_path}</code>
              </div>
              {approval.script_notice && <p className="approval-script-notice" role="note">{approval.script_notice}</p>}
            </div>
          )}
          {scriptContent && (
            <div className="approval-section">
              <button
                className="approval-link-button approval-link-button--toggle"
                onClick={() => setScriptExpanded(!scriptExpanded)}
              >
                <span className={scriptExpanded ? 'approval-link-button__arrow approval-link-button__arrow--open' : 'approval-link-button__arrow'}>&#9654;</span>
                {`View full script (${scriptLineCount} lines)`}
              </button>
              {approval.script_path && (
                <div className="approval-script-path">
                  <span className="approval-script-path__label">Script file</span>{' '}
                  <code>{approval.script_path}</code>
                </div>
              )}
              <CollapsibleRegion expanded={scriptExpanded}>
                <div className="command-display approval-script-preview">
                  {scriptContent}
                </div>
              </CollapsibleRegion>
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

          {/* Reason. A connected tool's reason is always that it is set to ask first, which is why the card is on screen at all, so it is left out. */}
          {!toolPolicy && (
            <p className="approval-reason">
              {approval.reason}
            </p>
          )}

          {/* What ticking Remember would store. Newer backends send the pattern with the whitelist status; older ones only send the generalized pattern. */}
          {approval.generalized_pattern && !rememberedPattern && !isSettingsChange && !toolPolicy && (
            <p className="approval-pattern">
              Pattern: {approval.generalized_pattern}
            </p>
          )}
          {!isProviderPermission && rememberAllowed && rememberedPattern && (
            <p className="approval-pattern approval-pattern--remembered">
              If remembered, Basil will approve any command that starts with{' '}
              <code className="approval-pattern__words">{rememberedPattern}</code>
            </p>
          )}
          {!isProviderPermission && rememberAllowed && approval.whitelist?.broad && (
            <p className="approval-pattern-broad" role="note">
              This is only the command name, so remembering it would approve every {rememberedPattern} command, not just this one. Leave it unticked unless that is what you want.
            </p>
          )}

          {/* Risk warning */}
          {approval.risk_level === 'high' && (
            <div className="approval-high-risk-notice">
              This command may cause permanent changes
            </div>
          )}

          {/* The note is rarely wanted, so it starts as a link and opens into the field. The same link closes it again; text already typed is kept and still sent, and the link says so. */}
          {noteAllowed && (
            <div className="approval-section">
              <button
                type="button"
                className="approval-link-button approval-note-toggle"
                aria-expanded={noteOpen}
                aria-controls={`approval-note-region-${approval.approval_id}`}
                disabled={submitting}
                onClick={() => setNoteOpen(!noteOpen)}
              >
                {noteOpen ? 'Hide note' : note.trim() ? 'Show your note (it will be sent)' : 'Add a note for the agent'}
              </button>
              <CollapsibleRegion expanded={noteOpen} id={`approval-note-region-${approval.approval_id}`} className="approval-note-region">
                <label className="approval-field-label" htmlFor={`approval-note-${approval.approval_id}`}>
                  Note to the agent (optional, sent with Approve or Deny)
                </label>
                <textarea
                  ref={noteInputRef}
                  id={`approval-note-${approval.approval_id}`}
                  className="approval-note-input"
                  rows={2}
                  maxLength={2000}
                  value={note}
                  disabled={submitting}
                  placeholder="For example: that file is in ~/Documents, not here. Or: approve, but also check the exit code."
                  onChange={e => setNote(e.target.value)}
                />
              </CollapsibleRegion>
            </div>
          )}

          {/* Remember choice */}
          {/* One sentence for a choice that can never be remembered. The reason already says Basil asks every time, so nothing else repeats it; an older backend that sends no reason gets the plain statement. */}
          {!isProviderPermission && !rememberAllowed && (
            <p className="approval-remember-blocked" role="note">
              {approval.whitelist?.reason || 'This approval applies to this run only.'}
            </p>
          )}
          {!isProviderPermission && rememberAllowed && (
            <label className="checkbox-row approval-remember">
              <input
                type="checkbox"
                checked={remember}
                onChange={e => setRemember(e.target.checked)}
                disabled={isBrowserSensitiveFill && !approval.browser_metadata?.will_remember_domain_allowed}
              />
              {isBrowserSensitiveFill
                ? 'Remember this domain'
                : toolPolicy
                  ? `Always allow ${toolPolicy.tool_name}${toolPolicy.connection_name ? ` on ${toolPolicy.connection_name}` : ''}`
                  : 'Remember this choice'}
            </label>
          )}
          {/* The agent's advice about the choice sits with the choice. It is never shown for a command that cannot be remembered, because the server replaces it there with the reason shown above. */}
          {!isProviderPermission && rememberAllowed && approval.whitelist?.advice && (
            <p className="approval-remember-advice">
              The agent recommends {approval.whitelist.advice.recommend ? 'remembering this' : 'asking each time'}: {approval.whitelist.advice.reason}
            </p>
          )}
          {/* Only once Always allow is ticked: what it will do, and that it is limited to this one tool and can be undone. */}
          {!isProviderPermission && rememberAllowed && toolPolicy && remember && (
            <p className={toolPolicy.destructive ? 'approval-tool-destructive' : 'approval-pattern approval-pattern--remembered'} role="note">
              {toolPolicy.destructive && <><strong>This tool deletes or sends things.</strong>{' '}</>}
              Basil will run <code className="approval-pattern__words">{toolPolicy.tool_name}</code> without asking again. This changes only this tool, and you can undo it in Settings → Connections.
            </p>
          )}

          {approval.time_limit && <ResponseCountdown timeLimit={approval.time_limit} />}
        </div>

        <DecisionActions className="approval-actions">
          {onMinimize && (
            <DecisionButton
              tone="neutral"
              icon={<ViewWorkCircleIcon />}
              label="See work so far"
              onClick={onMinimize}
              disabled={submitting}
              lead={!onStopTask}
              title="look over what Basil has done before you decide"
            />
          )}
          {onStopTask && (
            <DecisionButton
              tone="stop"
              icon={<StopCircleIcon />}
              label={isStopping ? 'Stopping' : 'Stop task'}
              onClick={onStopTask}
              disabled={isStopping}
              lead
              title="ends the whole task, the same as Stop in the header"
            />
          )}
          <DecisionButton
            tone="deny"
            icon={<DenyCircleIcon />}
            label="Deny"
            onClick={() => handleDecision(false)}
            disabled={submitting}
            title="refuse this one request. The task carries on and the agent can try another way"
          />
          <DecisionButton
            tone="approve"
            icon={<ApproveCircleIcon />}
            label="Approve"
            onClick={() => handleDecision(true)}
            disabled={submitting || !canApprove}
            title="let Basil run this"
          />
        </DecisionActions>
      </div>
    </div>
  );
}
