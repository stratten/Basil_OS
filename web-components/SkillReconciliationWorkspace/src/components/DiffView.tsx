interface DiffViewProps {
  beforeLabel: string;
  afterLabel: string;
  before: string;
  after: string;
}

export function DiffView({ beforeLabel, afterLabel, before, after }: DiffViewProps) {
  return (
    <div className="diff-view">
      <div className="diff-column before">
        <div className="diff-column-label">{beforeLabel}</div>
        <div className="diff-body">{before || '—'}</div>
      </div>
      <div className="diff-column after">
        <div className="diff-column-label">{afterLabel}</div>
        <div className="diff-body">{after || '—'}</div>
      </div>
    </div>
  );
}
