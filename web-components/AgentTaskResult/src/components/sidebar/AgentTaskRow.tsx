import { memo, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { useHistoryRowRevealDelete } from '@shared/useHistoryRowRevealDelete';
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
      <div className="sidebar-row sidebar-row--confirm-delete">
        <span className="sidebar-row-confirm__label">Delete this task?</span>
        <div className="sidebar-row-confirm__actions">
          <button
            type="button"
            className="sidebar-row-confirm__btn"
            onClick={(e) => { e.stopPropagation(); onCancelDeleteRequest?.(id); }}
          >
            Cancel
          </button>
          <button
            type="button"
            className="sidebar-row-confirm__btn sidebar-row-confirm__btn--danger"
            onClick={(e) => { e.stopPropagation(); onConfirmDelete?.(id); }}
          >
            Delete
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className={`sidebar-row ${isSelected ? 'selected' : ''}`}
        style={{ position: 'relative', overflow: 'hidden' }}
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
          style={{
            transform: revealDelete.offset > 0 ? `translateX(-${revealDelete.offset}px)` : undefined,
            transition: 'transform 0.15s ease',
            position: 'relative',
          }}
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
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); onRequestDelete(id); }}
              style={{
                position: 'absolute', top: 0, right: 'calc(-1 * var(--padding-s))',
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--error-base)', padding: '0 2px',
                display: 'flex', alignItems: 'center', zIndex: 1,
              }}
              title="Delete task"
            >
              <TrashIcon size={10} />
            </button>
          )}

          {hovered && onDetach && (
            <button
              className="agent-detach-btn"
              style={{ top: showTrash ? 14 : 0, right: 'calc(-1 * var(--padding-s))' }}
              onClick={(e) => { e.stopPropagation(); e.preventDefault(); onDetach(id); }}
              onDoubleClick={(e) => e.stopPropagation()}
              title="Open in separate window"
              aria-label="Open in separate window"
            >
              <OpenInSeparateWindowIcon size={10} />
            </button>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--padding-s)' }}>
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
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row-title" style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                {scheduledRunSourceTitle && (
                  <span
                    title={`From schedule: ${scheduledRunSourceTitle}`}
                    aria-label={`From schedule: ${scheduledRunSourceTitle}`}
                    style={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}
                  >
                    <ScheduledRunIcon />
                  </span>
                )}
                {originSourceLabel && (
                  <span
                    title={originSourceLabel}
                    aria-label={originSourceLabel}
                    style={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}
                  >
                    <ConversationOriginIcon />
                  </span>
                )}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
                  {title}
                </span>
              </div>
              {needsApproval && !isSelected ? (
                <div className="row-preview" style={{ color: 'var(--warning-base)' }}>Approval needed</div>
              ) : rowPreview ? (
                <div className="row-preview" style={isPaused ? { color: 'var(--warning-base)' } : undefined}>{rowPreview}</div>
              ) : null}
            </div>

            {needsApproval && !isSelected ? (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="var(--warning-base)" style={{ flexShrink: 0 }}>
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
              <div className="unread-badge" style={{ width: 8, height: 8, fontSize: 0 }} />
            ) : null}
          </div>

          {(dateStr || fileCount > 0 || followUpCount > 0) && (
            <div
              className="row-meta"
              style={{ marginLeft: 14, flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}
            >
              {(dateStr || fileCount > 0) && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--padding-xs)' }}>
                  {dateStr && <span>{dateStr}</span>}
                  {fileCount > 0 && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                      <DocIcon /> {fileCount}
                    </span>
                  )}
                </div>
              )}
              {followUpCount > 0 && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, color: 'rgba(51, 85, 155, 0.8)' }}>
                  <BranchIcon /> {followUpCount + 1} messages
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {showCancelConfirm && onCancel && (
        <div className="overlay-backdrop" onClick={() => setShowCancelConfirm(false)}>
          <div className="overlay-card" onClick={e => e.stopPropagation()} style={{ maxWidth: 320 }}>
            <div className="overlay-title">Cancel this task?</div>
            <div className="overlay-body">
              This will stop the task and remove it from the active list. Any progress will be lost.
            </div>
            <div className="overlay-actions">
              <button
                className="action-btn"
                onClick={() => setShowCancelConfirm(false)}
                style={{ background: 'var(--background-secondary)', color: 'var(--text-primary)' }}
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
