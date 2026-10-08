import { memo, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { useHistoryRowRevealDelete } from '@shared/useHistoryRowRevealDelete';
import { InlineDeleteConfirm } from '@shared/InlineDeleteConfirm';
import {
  BranchIcon,
  ConversationOriginIcon,
  DocIcon,
  OpenInSeparateWindowIcon,
  ScheduledRunIcon,
  StatusIcon,
  TrashIcon,
} from './SidebarIcons';
import { formatHistoryTimestamp, useDateDisplayStyle } from '../../app/dateDisplay';

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
  isSelected: boolean;
  onSelect: (id: string) => void;
  onDetach?: (id: string) => void;
  onCancel?: (id: string) => void;
  onRequestDelete?: (id: string) => void;
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
  isSelected,
  onSelect,
  onDetach,
  onCancel,
  onRequestDelete,
  onContextMenu,
  scheduledRunSourceTitle,
  originSourceLabel,
  isPendingDelete,
  onConfirmDelete,
  onCancelDeleteRequest,
}: AgentTaskRowProps) {
  const [hovered, setHovered] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const isActive = ['processing', 'routing', 'capturing', 'awaitingInput', 'paused'].includes(status);
  const isProcessingLike = status === 'processing' || status === 'routing' || status === 'capturing';
  const showCancel = isActive && hovered && !isSelected && !!onCancel;
  const showTrash = !isActive && hovered && !!onRequestDelete;
  const revealDelete = useHistoryRowRevealDelete({ enabled: !isActive && !!onRequestDelete });

  const isPaused = status === 'paused';
  const rowPreview = isPaused ? 'Paused' : currentStep || preview;

  const dateDisplayStyle = useDateDisplayStyle();
  const dateStr = timestamp ? formatHistoryTimestamp(timestamp, dateDisplayStyle) : '';

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

  if (isPendingDelete) {
    return (
      <InlineDeleteConfirm
        className="sidebar-row sidebar-row--confirm-delete"
        label="Delete this task?"
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

          <div className="agent-task-row__main">
            {needsApproval && !isSelected ? (
              <span className="approval-attention" />
            ) : isProcessingLike ? (
              <div className="pulsing-dots"><span /><span /><span /></div>
            ) : status === 'awaitingInput' ? (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="var(--warning-base)">
                <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm-.5 4.75v4.5a.75.75 0 0 0 1.5 0v-4.5a.75.75 0 0 0-1.5 0zM8 12a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"/>
              </svg>
            ) : status === 'paused' ? (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="var(--warning-base)" fillRule="evenodd" aria-label="Paused">
                <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zM6 4.75a.75.75 0 0 0-.75.75v5a.75.75 0 0 0 1.5 0v-5A.75.75 0 0 0 6 4.75zm4 0a.75.75 0 0 0-.75.75v5a.75.75 0 0 0 1.5 0v-5a.75.75 0 0 0-.75-.75z"/>
              </svg>
            ) : (
              <StatusIcon status={status} resultSeverity={resultSeverity} size={8} />
            )}
            <div className="agent-task-row__text">
              <div className="row-title agent-task-row__title">
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
                <span className="agent-task-row__title-text">
                  {title}
                </span>
              </div>
              {needsApproval && !isSelected ? (
                <div className="row-preview agent-task-row__preview--warning">Approval needed</div>
              ) : rowPreview ? (
                <div className={isPaused ? 'row-preview agent-task-row__preview--warning' : 'row-preview'}>{rowPreview}</div>
              ) : null}
            </div>

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
            ) : hasUnreadResult && !isSelected ? (
              <div className="unread-badge agent-task-row__unread" />
            ) : null}
          </div>

          {(dateStr || fileCount > 0 || followUpCount > 0) && (
            <div className="row-meta agent-task-row__meta">
              {(dateStr || fileCount > 0) && (
                <div className="agent-task-row__meta-line">
                  {dateStr && <span>{dateStr}</span>}
                  {fileCount > 0 && (
                    <span className="agent-task-row__meta-item">
                      <DocIcon /> {fileCount}
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
