import type { SettingsChangeApprovalMetadata } from '../../types';

interface Props {
  metadata?: SettingsChangeApprovalMetadata;
}

const cellStyle = { padding: '4px 8px', verticalAlign: 'top', overflowWrap: 'anywhere' } as const;

export default function SettingsChangeApprovalDetails({ metadata }: Props) {
  if (!metadata || metadata.changes.length === 0) return null;

  return (
    <div
      className="approval-section"
      data-testid="settings-change-details"
      style={{
        padding: 'var(--padding-s)',
        background: 'color-mix(in srgb, var(--processing-base) 10%, transparent)',
        borderRadius: 'var(--corner-radius-small)',
        border: '1px solid color-mix(in srgb, var(--processing-base) 30%, transparent)',
      }}
    >
      <div
        style={{
          fontSize: 'var(--font-size-status-small)',
          color: 'var(--text-primary)',
          marginBottom: 'var(--padding-xs)',
          fontWeight: 600,
        }}
      >
        An agent wants to change these Basil settings
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-status-small)' }}>
        <thead>
          <tr style={{ color: 'var(--text-secondary)', textAlign: 'left' }}>
            <th style={cellStyle}>Setting</th>
            <th style={cellStyle}>Now</th>
            <th style={cellStyle}>Change to</th>
          </tr>
        </thead>
        <tbody>
          {metadata.changes.map(change => (
            <tr key={change.key} style={{ color: 'var(--text-primary)' }}>
              <td style={cellStyle}>{change.label}</td>
              <td style={cellStyle}>{change.before}</td>
              <td style={{ ...cellStyle, fontWeight: 600 }}>{change.after}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
