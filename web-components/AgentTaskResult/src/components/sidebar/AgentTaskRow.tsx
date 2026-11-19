import { memo, useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import type { ScheduledRunNowOutcome } from '../../services/scheduledRunNow';
import { useHistoryRowRevealDelete } from '@shared/history/useHistoryRowRevealDelete';
import { InlineDeleteConfirm } from '@shared/dialogs/InlineDeleteConfirm';
import AgentTaskActiveIndicator from '@shared/status/AgentTaskActiveIndicator';
import NativeSymbolIcon from '@shared/icons/NativeSymbolIcon';
import { PlayCircleIcon } from '@shared/windowChrome/CircleControlIcons';
import {
  BranchIcon,
  ConversationOriginIcon,
  DocIcon,
  OpenInSeparateWindowIcon,
  ScheduledRunIcon,
  StatusIcon,
  TrashIcon,
} from './SidebarIcons';
import { formatTimestampForDisplay, useDateDisplayStyle } from '../../app/display/dateDisplay';
import { describeFollowUpDue } from '../../app/display/followUpTime';
import { useChecklistCounts } from '../../store/checklistStore';

export interface AgentTaskRowProps {
  id: string;
  title: string;
  status: string;
  resultSeverity?: string;
  preview?: string;
  currentStep?: string;
  timestamp?: string;
  fileCount: number;
  followUpCount: number;
  hasUnreadResult: boolean;
  needsApproval?: boolean;
  /** Specific wait copy for an unselected row, such as Token needed or Approval needed. */
  attentionPreview?: string;
  isSelected: boolean;
  onSelect: (id: string) => void;
  onDetach?: (id: string) => void;
  onCancel?: (id: string) => void;
  onRequestDelete?: (id: string) => void;
  // Archive (or, in the Archived view, restore) this row's chain. Offered only for rows that are not running.
  onArchive?: (id: string) => void;
  archiveLabel?: 'Archive' | 'Unarchive';
  onContextMenu?: (e: MouseEvent, id: string) => void;
  // When true, this row is mid-delete-confirmation: instead of its normal
  // content, it renders a compact inline "Delete this task?" prompt
  // with Cancel/Delete buttons in the same row box (no modal/backdrop).
  isPendingDelete?: boolean;
  onConfirmDelete?: (id: string) => void;
  onCancelDeleteRequest?: (id: string) => void;
  // When set, this row was produced by a scheduled agent task run. The value
  // is the parent schedule's title (used as the icon's tooltip so the user
  // can hover to see *which* schedule fired this row without taking up any
  // visible characters of the title text). When undefined, the row is a
  // normal user-initiated AgentTask.
  scheduledRunSourceTitle?: string;
  // When set, this row was produced by an Agent Task delegated from a Basil
  // Conversation turn. The value is a fixed display label (not the
  // conversation's title — no per-row conversation lookup is performed).
  originSourceLabel?: string;
  // ISO due time of this task's soonest scheduled follow-up check. While it is
  // set and the task is not actively running, the row shows a waiting state.
  nextFollowUpAt?: string;
  // Set only on rows that represent a schedule itself. True shows a solid green dot, false a hollow ring, so a schedule that has stopped firing is distinguishable at a glance.
  scheduleActive?: boolean;
  // Makes the schedule's status dot a switch, so a schedule can be activated or deactivated without opening it and scrolling to its Activate or Deactivate button. Receives the schedule's id and the active state to set, so a repeated click sends the same value instead of flipping it back.
  onToggleSchedule?: (id: string, nextActive: boolean) => void;
  // Offered on a schedule row, on hover, as a play button that starts one run now, whether or not the schedule is active. Resolves with whether the run started; the row shows the result in place of its preview line for a few seconds.
  onRunSchedule?: (id: string) => Promise<ScheduledRunNowOutcome>;
  // Question shown while this row awaits delete confirmation; defaults to the task wording.
  deleteConfirmLabel?: string;
  // The chain root whose checklist counter this row shows after the file count. Rows that are not a task chain (a schedule) leave it unset.
  checklistRootId?: string;
  // The counter from the history list, shown until a live update for the chain arrives.
  checklistDone?: number;
  checklistTotal?: number;
}

// Archive and Delete are revealed side by side, 60px each.
const SWIPE_ACTION_WIDTH_WITH_ARCHIVE = 120;

// How long a Run now result stays in place of the row's preview line. A failure stays longer because it says what to do.
const RUN_STARTED_NOTICE_MS = 3000;
const RUN_FAILED_NOTICE_MS = 6000;

interface RunNowNotice {
  kind: 'starting' | 'started' | 'failed';
  text: string;
}

function AgentTaskRowImpl({
  id,
  title,
  status,
  resultSeverity,
  preview,
  currentStep,
  timestamp,
  fileCount,
  followUpCount,
  hasUnreadResult,
  needsApproval,
  attentionPreview,
  isSelected,
  onSelect,
  onDetach,
  onCancel,
  onRequestDelete,
  onArchive,
  archiveLabel = 'Archive',
  onContextMenu,
  scheduledRunSourceTitle,
  originSourceLabel,
  nextFollowUpAt,
  isPendingDelete,
  onConfirmDelete,
  onCancelDeleteRequest,
  scheduleActive,
  onToggleSchedule,
  onRunSchedule,
  deleteConfirmLabel = 'Delete this task?',
  checklistRootId,
  checklistDone = 0,
  checklistTotal = 0,
}: AgentTaskRowProps) {
  const checklist = useChecklistCounts(checklistRootId, { done: checklistDone, total: checklistTotal });
  const showChecklist = Boolean(checklistRootId) && checklist.total > 0;
  const checklistLabel = `Checklist, ${checklist.done} of ${checklist.total} done${checklist.waitingUser > 0 ? `, ${checklist.waitingUser} waiting on you` : ''}`;
  const [hovered, setHovered] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const isActive = ['processing', 'routing', 'capturing', 'awaitingInput', 'paused'].includes(status);
  const showCancel = isActive && hovered && !isSelected && !!onCancel;
  const showTrash = !isActive && hovered && !!onRequestDelete;
  const [runNotice, setRunNotice] = useState<RunNowNotice | null>(null);
  const runNoticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runStarting = runNotice?.kind === 'starting';
  // Stays on screen while a run is starting, so moving the pointer away does not hide the button that was just pressed.
  const showRunNow = scheduleActive !== undefined && !!onRunSchedule && (hovered || runStarting);
  useEffect(() => () => {
    if (runNoticeTimer.current) clearTimeout(runNoticeTimer.current);
  }, []);
  const revealDelete = useHistoryRowRevealDelete({
    enabled: !isActive && !!onRequestDelete,
    actionWidth: onArchive ? SWIPE_ACTION_WIDTH_WITH_ARCHIVE : undefined,
  });

  const isPaused = status === 'paused';
  const followUpDue = nextFollowUpAt && !isActive ? describeFollowUpDue(nextFollowUpAt) : null;
  const rowPreview = isPaused ? 'Paused' : followUpDue ? followUpDue.rowText : currentStep || preview;

  const dateDisplayStyle = useDateDisplayStyle();
  const dateStr = timestamp ? formatTimestampForDisplay(timestamp, dateDisplayStyle) : '';

  const handleClick = () => {
    if (revealDelete.isOpen) {
      revealDelete.close();
      return;
    }
    onSelect(id);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    handleClick();
  };

  const handleDoubleClick = () => {
    if (!revealDelete.isOpen) onDetach?.(id);
  };

  const handleRunNow = async () => {
    if (!onRunSchedule || runStarting) return;
    if (runNoticeTimer.current) clearTimeout(runNoticeTimer.current);
    setRunNotice({ kind: 'starting', text: 'Starting run…' });
    const outcome = await onRunSchedule(id);
    setRunNotice(outcome.ok
      ? { kind: 'started', text: 'Run started' }
      : { kind: 'failed', text: outcome.message || 'Basil could not start this run.' });
    runNoticeTimer.current = setTimeout(() => setRunNotice(null), outcome.ok ? RUN_STARTED_NOTICE_MS : RUN_FAILED_NOTICE_MS);
  };

  if (isPendingDelete) {
    return (
      <InlineDeleteConfirm
        className="sidebar-row sidebar-row--confirm-delete"
        layout="stacked"
        label={deleteConfirmLabel}
        ariaLabel="Delete task"
        onCancel={() => onCancelDeleteRequest?.(id)}
        onConfirm={() => onConfirmDelete?.(id)}
      />
    );
  }

  return (
    <>
      <div
        className={`sidebar-row agent-task-row ${isSelected ? 'selected' : ''}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onContextMenu={onContextMenu ? (event) => onContextMenu(event, id) : undefined}
        onWheel={revealDelete.handleWheel}
      >
        {revealDelete.isOpen && onArchive && (
          <button
            className="swipe-archive-btn"
            onClick={(e) => {
              e.stopPropagation();
              revealDelete.close();
              onArchive(id);
            }}
          >
            {archiveLabel}
          </button>
        )}
        {revealDelete.isOpen && onRequestDelete && (
          <button
            className="swipe-delete-btn"
            onClick={(e) => {
              e.stopPropagation();
              revealDelete.close();
              onRequestDelete(id);
            }}
          >
            Delete
          </button>
        )}

        <div
          className="agent-task-row__slide"
          style={revealDelete.offset > 0 ? { transform: `translateX(-${revealDelete.offset}px)` } : undefined}
          role="button"
          tabIndex={0}
          aria-label={`${title}${rowPreview ? `. ${rowPreview}` : ''}`}
          aria-pressed={isSelected}
          onClick={handleClick}
          onKeyDown={handleKeyDown}
          onDoubleClick={handleDoubleClick}
        >
          {showTrash && onRequestDelete && (
            <button
              className="agent-task-row__trash"
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); onRequestDelete(id); }}
              title="Delete task"
            >
              <TrashIcon size={10} />
            </button>
          )}

          {hovered && onDetach && (
            <button
              className={`agent-detach-btn agent-task-row__detach${showTrash ? ' agent-task-row__detach--below-trash' : ''}`}
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); onDetach(id); }}
              onDoubleClick={(e) => e.stopPropagation()}
              title="Open in separate window"
              aria-label="Open in separate window"
            >
              <OpenInSeparateWindowIcon size={10} />
            </button>
          )}

          <div className="agent-task-row__main agent-task-row__main--aligned">
            <span className="agent-task-row__status-slot">
            {needsApproval && !isSelected ? (
              <span className="agent-task-processing-spinner agent-task-processing-spinner--attention approval-attention" />
            ) : isActive ? (
              <AgentTaskActiveIndicator
                status={status === 'awaitingInput' || status === 'paused' ? status : 'processing'}
              />
            ) : followUpDue ? (
              <span
                className="agent-task-row__waiting-icon"
                role="img"
                aria-label="Waiting to check again"
                title="Waiting to check again"
              >
                <NativeSymbolIcon name="refresh" size={11} />
              </span>
            ) : scheduleActive !== undefined ? (
              <>
                {onToggleSchedule ? (
                  <button
                    type="button"
                    className="agent-task-row__schedule-dot-btn"
                    role="switch"
                    aria-checked={scheduleActive}
                    aria-label="Schedule active"
                    title={scheduleActive ? 'Active. Click to deactivate' : 'Inactive. Click to activate'}
                    onClick={(e) => { e.stopPropagation(); e.preventDefault(); onToggleSchedule(id, !scheduleActive); }}
                    onDoubleClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <span className={`agent-task-row__schedule-dot ${scheduleActive ? 'is-active' : 'is-inactive'}`} aria-hidden="true" />
                  </button>
                ) : (
                  <span
                    className={`agent-task-row__schedule-dot ${scheduleActive ? 'is-active' : 'is-inactive'}`}
                    role="img"
                    aria-label={scheduleActive ? 'Schedule active' : 'Schedule inactive'}
                    title={scheduleActive ? 'Active' : 'Inactive'}
                  />
                )}
                {status === 'failed' && <StatusIcon status={status} resultSeverity={resultSeverity} size={8} />}
              </>
            ) : (
              <StatusIcon status={status} resultSeverity={resultSeverity} size={8} />
            )}
            </span>
            {(scheduledRunSourceTitle || originSourceLabel) && (
              <span className="agent-task-row__origin-slot">
                {scheduledRunSourceTitle && (
                  <span
                    className="agent-task-row__origin-icon"
                    title={`From schedule: ${scheduledRunSourceTitle}`}
                    aria-label={`From schedule: ${scheduledRunSourceTitle}`}
                  >
                    <ScheduledRunIcon />
                  </span>
                )}
                {originSourceLabel && (
                  <span
                    className="agent-task-row__origin-icon"
                    title={originSourceLabel}
                    aria-label={originSourceLabel}
                  >
                    <ConversationOriginIcon />
                  </span>
                )}
              </span>
            )}
            <div className="agent-task-row__text">
              <div className="row-title agent-task-row__title">
                <span className="agent-task-row__title-text">
                  {title}
                </span>
              </div>
              {needsApproval && !isSelected ? (
                <div className="row-preview agent-task-row__preview--warning">{attentionPreview || 'Approval needed'}</div>
              ) : runNotice ? (
                <div
                  className={runNotice.kind === 'failed' ? 'row-preview agent-task-row__preview--warning' : 'row-preview agent-task-row__preview--waiting'}
                  role="status"
                >
                  {runNotice.text}
                </div>
              ) : rowPreview ? (
                <div className={isPaused ? 'row-preview agent-task-row__preview--paused' : followUpDue ? 'row-preview agent-task-row__preview--waiting' : 'row-preview'}>{rowPreview}</div>
              ) : null}
            </div>

            {(needsApproval && !isSelected) || showCancel || showRunNow || (hasUnreadResult && !isSelected) ? (
              <span className="agent-task-row__trailing">
                {needsApproval && !isSelected ? (
                  <svg className="agent-task-row__alert-icon" width="12" height="12" viewBox="0 0 16 16" fill="var(--warning-base)">
                    <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm-.5 4.75v4.5a.75.75 0 0 0 1.5 0v-4.5a.75.75 0 0 0-1.5 0zM8 12a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"/>
                  </svg>
                ) : showCancel ? (
                  <button
                    className="agent-cancel-btn"
                    onClick={(e) => { e.stopPropagation(); setShowCancelConfirm(true); }}
                    title="Cancel this task"
                  >
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="var(--error-base)" opacity="0.8">
                      <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm2.12 4.88a.75.75 0 0 0-1.06 0L8 5.94 6.94 4.88a.75.75 0 1 0-1.06 1.06L6.94 7 5.88 8.06a.75.75 0 1 0 1.06 1.06L8 8.06l1.06 1.06a.75.75 0 1 0 1.06-1.06L9.06 7l1.06-1.06a.75.75 0 0 0 0-1.06z"/>
                    </svg>
                  </button>
                ) : showRunNow ? (
                  <button
                    className="agent-schedule-run-btn"
                    disabled={runStarting}
                    onClick={(e) => { e.stopPropagation(); e.preventDefault(); void handleRunNow(); }}
                    onDoubleClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                    title="Run now"
                    aria-label="Run this schedule now"
                  >
                    <PlayCircleIcon />
                  </button>
                ) : (
                  <div className="unread-badge agent-task-row__unread" />
                )}
              </span>
            ) : null}
          </div>

          {(dateStr || fileCount > 0 || showChecklist || followUpCount > 0) && (
            <div className="row-meta agent-task-row__meta">
              {(dateStr || fileCount > 0 || showChecklist) && (
                <div className="agent-task-row__meta-line">
                  {dateStr && <span>{dateStr}</span>}
                  {fileCount > 0 && (
                    <span className="agent-task-row__meta-item">
                      <DocIcon /> {fileCount}
                    </span>
                  )}
                  {showChecklist && (
                    <span
                      className={`agent-task-row__meta-item agent-task-row__checklist${checklist.waitingUser > 0 ? ' is-attention' : ''}`}
                      title={checklistLabel}
                      aria-label={checklistLabel}
                    >
                      <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <rect x="2" y="2" width="12" height="12" rx="2.5" />
                        <path d="m5 8.2 2 2 4-4.4" />
                      </svg>
                      {checklist.done}/{checklist.total}
                    </span>
                  )}
                </div>
              )}
              {followUpCount > 0 && (
                <span className="agent-task-row__meta-item agent-task-row__meta-item--thread">
                  <BranchIcon /> {followUpCount + 1} messages
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {showCancelConfirm && onCancel && (
        <div className="overlay-backdrop" onClick={() => setShowCancelConfirm(false)}>
          <div className="overlay-card agent-task-row__cancel-card" onClick={e => e.stopPropagation()}>
            <div className="overlay-title">Cancel this task?</div>
            <div className="overlay-body">
              This will stop the task and remove it from the active list. Any progress will be lost.
            </div>
            <div className="overlay-actions">
              <button
                className="action-btn action-btn--neutral"
                onClick={() => setShowCancelConfirm(false)}
              >
                Keep
              </button>
              <button className="action-btn danger" onClick={() => { setShowCancelConfirm(false); onCancel(id); }}>
                Cancel task
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export const AgentTaskRow = memo(AgentTaskRowImpl);
