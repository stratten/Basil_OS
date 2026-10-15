interface CompanionInvestigationNoticeProps {
  /** How many investigations are running, from the Companion status. */
  running: number;
  /** The question of the most recent investigation that has produced no answer, when the timeline recorded it. */
  question: string | null;
  onStop: () => Promise<boolean>;
}

/** The "Investigating" notice with its Stop action; it only exists while the backend reports a running investigation. */
export default function CompanionInvestigationNotice({ running, question, onStop }: CompanionInvestigationNoticeProps) {
  if (!(running > 0)) return null;
  return (
    <div className="meeting-status-row companion-notice-row companion-investigation-notice" role="status">
      <span className="meeting-connection-indicator meeting-connection-indicator--ready" aria-hidden="true" />
      <span className="meeting-status-message">
        {running === 1 ? 'Investigating' : `Investigating ${running} questions`}
        {question ? `: ${question}` : ''}
      </span>
      <button type="button" className="meeting-history-load-more-button" onClick={() => void onStop()}>Stop</button>
    </div>
  );
}
