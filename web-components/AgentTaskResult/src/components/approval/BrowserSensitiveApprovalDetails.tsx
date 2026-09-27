import type { BrowserSensitiveApprovalMetadata } from '../../types';

interface Props {
  metadata?: BrowserSensitiveApprovalMetadata;
}

export default function BrowserSensitiveApprovalDetails({ metadata }: Props) {
  if (!metadata) return null;

  const detailRows = [
    ['Domain', metadata.domain],
    ['Browser', metadata.browser],
    ['Field', metadata.field_label],
    ['Field type', metadata.field_type],
    ['Value source', metadata.value_source],
  ].filter(([, value]) => typeof value === 'string' && value.length > 0);

  return (
    <div
      style={{
        marginBottom: 'var(--padding-m)',
        padding: 'var(--padding-s)',
        background: 'rgba(147, 130, 220, 0.10)',
        borderRadius: 'var(--corner-radius-small)',
        border: '1px solid rgba(147, 130, 220, 0.25)',
      }}
    >
      <div
        style={{
          fontSize: 'var(--font-size-status-small)',
          color: 'var(--text-secondary)',
          marginBottom: 'var(--padding-xs)',
          fontWeight: 600,
        }}
      >
        Browser sensitive fill
      </div>
      {detailRows.map(([label, value]) => (
        <div
          key={label}
          style={{
            display: 'flex',
            gap: 8,
            fontSize: 'var(--font-size-status-small)',
            marginTop: 4,
          }}
        >
          <span style={{ color: 'var(--text-tertiary)', minWidth: 88 }}>{label}:</span>
          <span style={{ color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>{value}</span>
        </div>
      ))}
      {metadata.url && (
        <div
          style={{
            marginTop: 'var(--padding-xs)',
            color: 'var(--text-tertiary)',
            fontSize: 'var(--font-size-status-small)',
            overflowWrap: 'anywhere',
          }}
        >
          {metadata.url}
        </div>
      )}
    </div>
  );
}

