import { useMemo } from 'react';
import { formatHistoryTimestamp, useDateDisplayStyle } from '../../app/dateDisplay';
import { TURN_STATUS_LABELS, type TurnStatus } from './turnPresentation';

const GLYPH_PATHS: Record<TurnStatus, string> = {
  success: 'm4.8 8.2 2.2 2.2 4.2-4.6',
  partial: 'M5 8h6',
  failed: 'm5.5 5.5 5 5M10.5 5.5l-5 5',
  active: 'M8 5v3l2 1.5',
};

export function TurnStatusGlyph({ status, tooltip }: { status: TurnStatus; tooltip?: string }) {
  return (
    <svg
      className={`turn-status-glyph turn-status-glyph--${status}`}
      data-tooltip={tooltip}
      width="11"
      height="11"
      viewBox="0 0 16 16"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="7.25" />
      <path d={GLYPH_PATHS[status]} />
    </svg>
  );
}

interface TurnLabelProps {
  runId: string;
  label: string;
  status: TurnStatus;
  timestamp?: string;
  isFocused: boolean;
  onFocusRun?: (runId: string) => void;
}

export function TurnLabel({ runId, label, status, timestamp, isFocused, onFocusRun }: TurnLabelProps) {
  const dateDisplayStyle = useDateDisplayStyle();
  const timeText = useMemo(
    () => (timestamp ? formatHistoryTimestamp(timestamp, dateDisplayStyle) : ''),
    [timestamp, dateDisplayStyle],
  );
  const statusLabel = TURN_STATUS_LABELS[status];
  const content = (
    <>
      <TurnStatusGlyph status={status} tooltip={statusLabel} />
      <span className="turn-label-text">{label}</span>
      {timeText && <span className="turn-label-time">{timeText}</span>}
    </>
  );

  if (!onFocusRun) {
    return <div className="turn-label" data-run-anchor={runId}>{content}</div>;
  }

  return (
    <button
      type="button"
      data-run-anchor={runId}
      className={`turn-label turn-label--interactive${isFocused ? ' is-focused' : ''}`}
      aria-pressed={isFocused}
      aria-label={`${label}, ${statusLabel}. Show this run's overview`}
      onClick={event => {
        event.stopPropagation();
        onFocusRun(runId);
      }}
    >
      {content}
    </button>
  );
}
