import type { ExclusionWindow } from '../../types';
import { WEEKDAY_LABELS } from './scheduledAgentTaskHelpers';
import {
  MAX_EXCLUSION_WINDOWS,
  exclusionWindowsError,
  newExclusionWindow,
  toggleWindowDay,
} from './scheduledChainHelpers';

export const EXCLUSIONS_LABEL = 'Quiet hours';

const EXCLUSIONS_HELP =
  'The schedule does not run during these times, read in the schedule timezone. A window that ends earlier than it starts crosses midnight. The weekdays you pick are the days the window starts on; with none picked it applies every day.';

interface Props {
  windows: ExclusionWindow[];
  onChange: (next: ExclusionWindow[]) => void;
  disabled?: boolean;
}

const rowStyle = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 8,
  fontFamily: 'var(--font-family-light)',
  fontSize: 'var(--font-size-callout)',
  color: 'var(--text-primary)',
} as const;

const labelStyle = { fontFamily: 'var(--font-family-medium)', color: 'var(--text-tertiary)', minWidth: 72, paddingTop: 4 } as const;

// The "Quiet hours" rows of the create and edit forms: any number of daily windows, up to eight, in which a recurring schedule does not start a run. Each window has a start, an end, and optionally the weekdays it starts on.
export default function ScheduledExclusionWindowsField({ windows, onChange, disabled }: Props) {
  const error = exclusionWindowsError(windows);
  const update = (index: number, next: ExclusionWindow) => onChange(windows.map((entry, i) => (i === index ? next : entry)));
  return (
    <div style={rowStyle}>
      <span style={labelStyle} title={EXCLUSIONS_HELP}>
        {EXCLUSIONS_LABEL}
      </span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 0 }}>
        {windows.map((window, index) => {
          const days = window.days ?? [];
          return (
            <div
              key={index}
              role="group"
              aria-label={`Quiet hours window ${index + 1}`}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                padding: 8,
                border: '1px solid var(--separator-color)',
                borderRadius: 'var(--corner-radius-small)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span>Do not run from</span>
                <input
                  className="sidebar-search-input schedule-time-input"
                  type="time"
                  value={window.start}
                  disabled={disabled}
                  onChange={event => update(index, { ...window, start: event.target.value })}
                  style={{ flex: '0 0 120px' }}
                  aria-label={`Quiet hours ${index + 1} start`}
                />
                <span>until</span>
                <input
                  className="sidebar-search-input schedule-time-input"
                  type="time"
                  value={window.end}
                  disabled={disabled}
                  onChange={event => update(index, { ...window, end: event.target.value })}
                  style={{ flex: '0 0 120px' }}
                  aria-label={`Quiet hours ${index + 1} end`}
                />
                <button
                  type="button"
                  className="action-btn"
                  disabled={disabled}
                  onClick={() => onChange(windows.filter((_, i) => i !== index))}
                  aria-label={`Remove quiet hours window ${index + 1}`}
                >
                  Remove
                </button>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {WEEKDAY_LABELS.map((label, day) => {
                  const selected = days.includes(day);
                  return (
                    <button
                      key={label}
                      type="button"
                      disabled={disabled}
                      onClick={() => update(index, toggleWindowDay(window, day))}
                      aria-pressed={selected}
                      aria-label={`${label} for quiet hours window ${index + 1}`}
                      style={{
                        flex: '1 1 0',
                        minWidth: 40,
                        padding: '4px 6px',
                        border: '1px solid var(--separator-color)',
                        borderRadius: 'var(--corner-radius-small)',
                        background: selected ? 'rgba(51, 85, 155, 0.85)' : 'var(--background-tertiary)',
                        color: selected ? 'white' : 'var(--text-primary)',
                        fontFamily: 'var(--font-family-medium)',
                        fontSize: 'var(--font-size-status-small)',
                        cursor: disabled ? 'default' : 'pointer',
                      }}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <span>{days.length > 0 ? 'Starting on the selected days only.' : 'Every day.'}</span>
            </div>
          );
        })}
        <div>
          <button
            type="button"
            className="action-btn"
            disabled={disabled || windows.length >= MAX_EXCLUSION_WINDOWS}
            onClick={() => onChange([...windows, newExclusionWindow()])}
          >
            Add quiet hours
          </button>
        </div>
        {error && (
          <span role="alert" style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-family-medium)' }}>
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
