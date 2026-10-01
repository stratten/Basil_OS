import { useState } from 'react';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import { runDetailsHint, type RunDetailItem } from './resultContentUtils';

export function RunDetailsDisclosure({ details }: { details: RunDetailItem[] }) {
  const [expanded, setExpanded] = useState(false);
  if (details.length === 0) return null;
  const hint = runDetailsHint(details);

  return (
    <div className="run-details" onClick={event => event.stopPropagation()}>
      <button
        type="button"
        className="run-details-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded(current => !current)}
      >
        <span className="run-details-title">Run details</span>
        {hint && <span className="run-details-hint">{hint}</span>}
        <ExecutionDisclosureChevron expanded={expanded} color="var(--secondary)" />
      </button>
      {expanded && (
        <dl className="run-details-list">
          {details.map(detail => (
            <div className="run-details-row" key={`${detail.key}:${detail.value}`}>
              <dt>{detail.label}</dt>
              <dd>{detail.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
