import type { ProgressState, SessionStatus } from '../types';

interface ProgressBannerProps {
  progress: ProgressState;
  status: SessionStatus;
}

export function ProgressBanner({ progress, status }: ProgressBannerProps) {
  const total = Math.max(progress.total, 0);
  const processed = Math.min(progress.processed, total || progress.processed);
  const pct = total > 0 ? Math.round((processed / total) * 100) : status === 'analyzing' ? 0 : 100;

  const phaseLabel =
    status === 'analyzing'
      ? 'Analyzing candidates…'
      : status === 'committing'
        ? 'Committing…'
        : status === 'committed'
          ? 'Committed'
          : 'Ready for review';

  return (
    <div className="progress-banner">
      <span className="progress-phase">{phaseLabel}</span>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {total > 0 && (
        <span className="progress-count">
          {processed}/{total}
        </span>
      )}
    </div>
  );
}
