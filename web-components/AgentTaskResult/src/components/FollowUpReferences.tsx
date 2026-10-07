interface Props {
  paths: string[];
  onRemove: (index: number) => void;
}

function basename(path: string): string {
  return path.split('/').pop() || path;
}

/** The files and folders attached to a follow-up or run note, each removable before it is sent. */
export default function FollowUpReferences({ paths, onRemove }: Props) {
  if (paths.length === 0) return null;
  return (
    <div className="text-followup-references" style={{
      display: 'flex', flexDirection: 'column', gap: 2,
      margin: '4px var(--padding-xs) 0',
      padding: '3px var(--padding-xs)',
      borderRadius: 'var(--corner-radius-small)',
      background: 'color-mix(in srgb, var(--background-secondary) 50%, transparent)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 4, height: 12, padding: '0 4px',
        color: 'var(--text-tertiary)', fontFamily: 'var(--font-family-light)', fontSize: 'var(--font-size-status-tiny)',
      }}>
        <svg width="9" height="9" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
        </svg>
        <span>References</span>
      </div>
      {paths.map((path, index) => (
        <div key={`${path}-${index}`} style={{ display: 'flex', alignItems: 'center', gap: 4, height: 18, padding: '0 4px', minWidth: 0 }}>
          <svg width="9" height="9" viewBox="0 0 16 16" fill="color-mix(in srgb, var(--secondary) 70%, transparent)" aria-hidden="true">
            <path d="M3 1h6l4 4v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1Z" />
            <path d="M9 1v4h4" fill="none" stroke="var(--background-secondary)" strokeWidth="0.8" />
          </svg>
          <span title={path} style={{
            flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            color: 'var(--primary)', fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-tiny)', textDecoration: 'underline',
          }}>{basename(path)}</span>
          <button type="button" onClick={() => onRemove(index)} aria-label={`Remove ${basename(path)}`} title={`Remove ${basename(path)}`} style={{
            flex: '0 0 auto', padding: 0, border: 0, background: 'transparent', color: 'var(--text-tertiary)',
            fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-tiny)', lineHeight: 1, cursor: 'pointer',
          }}>✕</button>
        </div>
      ))}
    </div>
  );
}
