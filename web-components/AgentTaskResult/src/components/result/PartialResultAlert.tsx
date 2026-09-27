import MarkdownRenderer from '../MarkdownRenderer';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';

interface PartialResultAlertProps {
  message: string;
  isCollapsed: boolean;
  onToggle: () => void;
  severity?: string;
  outcome?: string;
}

export function PartialResultAlert({
  message,
  isCollapsed,
  onToggle,
  severity,
  outcome,
}: PartialResultAlertProps) {
  const firstMeaningfulLine = message.split('\n').map((line) => line.trim()).find(Boolean);
  const previewText = firstMeaningfulLine || 'Partial result available';
  const normalizedOutcome = (outcome || '').toLowerCase();
  if (normalizedOutcome === 'completed_with_warnings') return null;
  const headerLabel =
    severity === 'error'
      ? "Couldn't complete"
      : normalizedOutcome === 'partial'
          ? 'Partial result'
          : 'Partial result alert';
  const alertColor = severity === 'warning' ? 'var(--warning-base)' : 'var(--error-base)';
  const alertBorder = severity === 'warning'
    ? '1px solid rgba(198, 121, 0, 0.28)'
    : '1px solid rgba(139, 0, 0, 0.3)';

  return (
    <div style={{
      padding: 'var(--padding-m)',
      margin: '0 var(--padding-xs) var(--padding-m)',
      background: 'var(--background-primary)',
      borderRadius: 'var(--corner-radius-medium, 8px)',
      border: alertBorder,
    }}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 'var(--padding-s)',
          width: '100%',
          padding: 0,
          border: 'none',
          background: 'transparent',
          color: alertColor,
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill={alertColor} style={{ flexShrink: 0, marginTop: 2 }}>
          <path d="M8.982 1.566a1.13 1.13 0 0 0-1.964 0L.165 13.233c-.457.778.091 1.767.982 1.767h13.706c.891 0 1.439-.99.982-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
        </svg>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontFamily: 'var(--font-family-medium)',
            fontSize: 'var(--font-size-callout)',
          }}>
            {headerLabel}
          </div>
          {isCollapsed && (
            <div style={{
              marginTop: 2,
              fontFamily: 'var(--font-family-light)',
              fontSize: 'var(--font-size-status-small)',
              color: 'var(--text-secondary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {previewText}
            </div>
          )}
        </div>
        <span style={{ flexShrink: 0, marginTop: 3 }}>
          <ExecutionDisclosureChevron expanded={!isCollapsed} color={alertColor} />
        </span>
      </button>

      {!isCollapsed && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--padding-s)', marginTop: 'var(--padding-s)' }}>
          <div style={{ width: 12, flexShrink: 0 }} />
          {/* The agent frequently emits clarification / failure text formatted
              as markdown (bold question stems, numbered lists, sub-bullets —
              see the "schedule an email at 8am" failure case). Rendering it as
              a plain <span> left literal **, 1., - characters in the UI, which
              both looked broken and made the message harder to scan. We pipe
              the same string through MarkdownRenderer (already used for the
              main result body) and wrap it in a div that pins ``color`` to the
              error tint — markdown inherits color through every block element
              we care about (p/li/strong/em/h*) so the entire rendered tree
              stays visually associated with the error banner without us having
              to override styles per element. ``error-markdown`` is just a
              hook for any future scoped CSS overrides; today it's
              presentational only. */}
          <div className="error-markdown" style={{
            color: alertColor,
            fontFamily: 'var(--font-family-light)',
            fontSize: 'var(--font-size-callout)',
            userSelect: 'text',
            flex: 1,
            minWidth: 0,
          }}>
            <MarkdownRenderer content={message} />
          </div>
        </div>
      )}
    </div>
  );
}
