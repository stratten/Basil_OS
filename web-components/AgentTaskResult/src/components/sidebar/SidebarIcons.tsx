// --- SVG Icon Components (matching original SF Symbols) ---

export function StatusIcon({
  status,
  size = 8,
  resultSeverity,
}: {
  status: string;
  size?: number;
  resultSeverity?: string;
}) {
  if (resultSeverity === 'warning') {
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" style={{ flexShrink: 0 }}>
        <circle cx="8" cy="8" r="8" fill="var(--warning-base)" />
        <path d="M8 4.25v4.5M8 11.75h.01" stroke="white" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  if (status === 'completed' || resultSeverity === 'success') {
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" style={{ flexShrink: 0 }}>
        <circle cx="8" cy="8" r="8" fill="var(--success-base)" />
        <path d="M4.5 8L7 10.5L11.5 5.5" stroke="white" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === 'failed' || resultSeverity === 'error') {
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" style={{ flexShrink: 0 }}>
        <circle cx="8" cy="8" r="8" fill="var(--error-base)" />
        <path d="M5.5 5.5L10.5 10.5M10.5 5.5L5.5 10.5" stroke="white" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  if (status === 'processing') {
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" style={{ flexShrink: 0 }}>
        <circle cx="8" cy="8" r="8" fill="orange" />
        <path d="M6 4.5h4M6 11.5h4M6.5 4.5L8 7.5 9.5 4.5M6.5 11.5L8 8.5 9.5 11.5" stroke="white" strokeWidth="1.0" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" style={{ flexShrink: 0 }}>
      <circle cx="8" cy="8" r="8" fill="gray" />
    </svg>
  );
}

export function BranchIcon() {
  return (
    <svg width="8" height="8" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <circle cx="8" cy="3" r="1.5" />
      <circle cx="4" cy="13" r="1.5" />
      <circle cx="12" cy="13" r="1.5" />
      <path d="M8 4.5v2.5c0 2-4 2-4 4.5M8 7c0 2 4 2 4 4.5" />
    </svg>
  );
}

export function DocIcon() {
  return (
    <svg width="8" height="8" viewBox="0 0 14 16" fill="currentColor" style={{ flexShrink: 0 }}>
      <path d="M3 0C1.9 0 1 .9 1 2v12c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V5L8 0H3z" />
    </svg>
  );
}

/**
 * Small clock glyph used as the inline badge that marks a history row as
 * having been produced by a scheduled agent task rather than a live voice
 * capture. Sized to match the surrounding metadata icons (Branch/Doc) so
 * it doesn't visually dominate the row, and uses ``currentColor`` /
 * ``var(--secondary)`` instead of a hard-coded fill so it adapts to the
 * panel's theme without a separate dark-mode pass.
 *
 * Why a glyph instead of the prior ``"Scheduled • "`` text prefix:
 * the prefix ate visible characters of the actual AgentTask title in narrow
 * sidebar widths, and a leading badge is faster to scan when the user is
 * triaging a long history list looking for one specific scheduled-run
 * result.
 */
export function ScheduledRunIcon() {
  return (
    <svg
      width="9"
      height="9"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, color: 'var(--secondary)' }}
    >
      <circle cx="8" cy="8" r="6.5" />
      <path d="M8 4.5V8l2.5 1.5" />
    </svg>
  );
}

/**
 * Small chat-bubble glyph marking a history row as having been delegated
 * from a Basil Conversation turn rather than a direct voice/manual capture.
 * Sized and styled identically to ScheduledRunIcon so multiple provenance
 * badges can sit side-by-side without visual imbalance.
 */
export function ConversationOriginIcon() {
  return (
    <svg
      width="9"
      height="9"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, color: 'var(--secondary)' }}
    >
      <path d="M2 3.5h12v7.5H6.5L3.5 13.5V11H2V3.5z" />
    </svg>
  );
}

export function TrashIcon({ size = 10 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="0.8`" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d="M2.5 4h11M5.5 4V2.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V4" />
      <path d="M3.5 4l.7 9.5a1 1 0 0 0 1 .9h5.6a1 1 0 0 0 1-.9L12.5 4" />
      <line x1="6.5" y1="7" x2="6.5" y2="12" />
      <line x1="9.5" y1="7" x2="9.5" y2="12" />
    </svg>
  );
}

export function OpenInSeparateWindowIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0 }}
    >
      <rect x="2.5" y="4.5" width="9" height="9" rx="1" />
      <path d="M8 2.5h5.5V8M13.5 2.5 7.5 8.5" />
    </svg>
  );
}

export function PlusCircleIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" style={{ flexShrink: 0 }}>
      <circle cx="8" cy="8" r="7" />
      <line x1="8" y1="4.5" x2="8" y2="11.5" />
      <line x1="4.5" y1="8" x2="11.5" y2="8" />
    </svg>
  );
}

export function MicrophoneIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <rect x="5.5" y="1" width="5" height="8" rx="2.5" />
      <path d="M3.5 7a4.5 4.5 0 0 0 9 0" />
      <line x1="8" y1="11.5" x2="8" y2="14" />
      <line x1="5.5" y1="14" x2="10.5" y2="14" />
    </svg>
  );
}

export function WarningIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" style={{ flexShrink: 0 }}>
      <path d="M7.13 1.66a1 1 0 0 1 1.74 0l6 10.5A1 1 0 0 1 14 13.5H2a1 1 0 0 1-.87-1.34z" fill="var(--warning-base)" />
      <line x1="8" y1="6" x2="8" y2="9.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="8" cy="11.2" r="0.7" fill="white" />
    </svg>
  );
}

export function SidebarIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.0" strokeLinecap="round">
      <line x1="2" y1="4" x2="14" y2="4" />
      <line x1="2" y1="8" x2="14" y2="8" />
      <line x1="2" y1="12" x2="14" y2="12" />
    </svg>
  );
}

export function CalendarIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.0" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2.5" y="3.5" width="11" height="10" rx="1.5" />
      <line x1="5" y1="2.5" x2="5" y2="4.5" />
      <line x1="11" y1="2.5" x2="11" y2="4.5" />
      <line x1="2.5" y1="6" x2="13.5" y2="6" />
    </svg>
  );
}
