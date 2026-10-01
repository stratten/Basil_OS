import { useId, useState } from 'react';
import type { DelegatedProviderReportCard } from '../../artifacts/artifactContract';

export interface DelegatedProviderReportCardsProps {
  cards: DelegatedProviderReportCard[];
}

type DelegatedWorkState = 'working' | 'review' | 'verified' | 'completed';

function delegatedWorkState(cards: DelegatedProviderReportCard[]): DelegatedWorkState {
  if (cards.some((card) => (
    card.runStatus === 'failed'
    || card.runStatus === 'canceled'
    || card.runStatus === 'interrupted'
    || card.captureState === 'unavailable'
    || card.verificationState === 'verification_mismatch'
  ))) {
    return 'review';
  }
  if (cards.some((card) => (
    card.runStatus === 'admitted'
    || card.runStatus === 'running'
    || card.runStatus === 'waiting_user_input'
    || card.runStatus === 'waiting_permission'
    || card.runStatus === 'supervision_due'
    || card.runStatus === 'canceling'
    || card.verificationState === 'pending'
  ))) {
    return 'working';
  }
  if (cards.every((card) => card.verificationState === 'verified')) {
    return 'verified';
  }
  return 'completed';
}

function delegatedWorkLabel(state: DelegatedWorkState): string {
  switch (state) {
    case 'working': return 'In progress';
    case 'review': return 'Needs review';
    case 'verified': return 'Verified';
    case 'completed': return 'Completed';
  }
}

function readable(value: string): string {
  return value.replace(/_/g, ' ');
}

export function DelegatedProviderReportCards({ cards }: DelegatedProviderReportCardsProps) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  if (cards.length === 0) return null;
  const state = delegatedWorkState(cards);
  const countLabel = `${cards.length} ${cards.length === 1 ? 'run' : 'runs'}`;
  return (
    <section
      className={`delegated-provider-work-chip delegated-provider-work-chip--${state}`}
      aria-label={`Delegated work: ${countLabel}, ${delegatedWorkLabel(state)}`}
    >
      <button
        type="button"
        className="delegated-provider-work-chip-toggle"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="delegated-provider-work-chip-indicator" aria-hidden="true" />
        <span className="delegated-provider-work-chip-label">Delegated work</span>
        <span className="delegated-provider-work-chip-count">{countLabel}</span>
        <span className="delegated-provider-work-chip-state">{delegatedWorkLabel(state)}</span>
        <span className="delegated-provider-work-chip-disclosure" aria-hidden="true">{expanded ? '⌃' : '⌄'}</span>
      </button>
      {expanded && (
        <ul id={detailsId} className="delegated-provider-work-details" aria-label="Delegated run details">
          {cards.map((card, index) => (
            <li key={card.delegatedAgentRunId}>
              <span className="delegated-provider-work-details-label">Provider run {index + 1}</span>
              <span>{readable(card.runStatus)} · {readable(card.verificationState)}</span>
              {card.latestSummary && <span className="delegated-provider-work-details-summary">{card.latestSummary}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
