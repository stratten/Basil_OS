import { formatClockSeconds } from '@shared/formatClockSeconds';
import { consideredHeadline, outcomeLabel, parseEvaluationEvent, triggerLabel, waitLabel } from './companionEvaluations';
import type { TimelineEvent } from './types';

interface CompanionConsideredRowProps {
  event: TimelineEvent;
}

/** One quiet row for an evaluation: what the Companion weighed, whether it spoke, and why a candidate was held back. */
export default function CompanionConsideredRow({ event }: CompanionConsideredRowProps) {
  const record = parseEvaluationEvent(event);
  const spoke = record.kept > 0 && record.discarded === null;
  const hasDetail = record.candidates.length > 0 || record.gateWaits.length > 0 || record.discarded !== null;
  return (
    <div className={`companion-considered${spoke ? ' is-spoke' : ''}${record.error !== null ? ' is-error' : ''}`} role="note" aria-label={`Considered at ${formatClockSeconds(event.meeting_time, { padMinutes: true })}`}>
      <p className="companion-considered-headline">
        <span className="companion-considered-time">[{formatClockSeconds(event.meeting_time, { padMinutes: true })}]</span>
        <span className="companion-considered-trigger">Looked at {triggerLabel(record.trigger)}{record.newLines > 0 ? `, ${record.newLines} new ${record.newLines === 1 ? 'line' : 'lines'}` : ''}</span>
        <span className="companion-considered-verdict">{spoke ? 'Spoke' : 'Stayed quiet'}</span>
      </p>
      <p className="companion-considered-text">{consideredHeadline(record)}</p>
      {hasDetail && (
        <details className="companion-considered-detail">
          <summary>Details</summary>
          {record.discarded !== null && <p className="companion-item-note">The result arrived too late and was thrown away.</p>}
          {record.candidates.length > 0 && (
            <ul>
              {record.candidates.map((candidate, index) => (
                <li key={`${index}:${candidate.text}`}>
                  <strong>{outcomeLabel(candidate.outcome)}</strong> ({Math.round(candidate.confidence * 100)}% sure): {candidate.text}
                </li>
              ))}
            </ul>
          )}
          {record.gateWaits.length > 0 && (
            <p className="companion-item-note">Before this check: {record.gateWaits.map((wait) => `${waitLabel(wait.reason)} x${wait.count}`).join(', ')}.</p>
          )}
        </details>
      )}
    </div>
  );
}
