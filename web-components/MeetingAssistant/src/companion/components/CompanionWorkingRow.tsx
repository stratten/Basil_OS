interface CompanionWorkingRowProps {
  /** True while the fast evaluator is deciding whether to speak. */
  evaluating: boolean;
  /** How many investigations are running, from the Companion status. */
  investigating: number;
  /** The question of the most recent investigation that has produced no answer, when the timeline recorded it. */
  question: string | null;
  onStop: () => Promise<boolean>;
}

/** The live row at the end of the stream: "Researching" (with Stop) while an investigation runs, otherwise "Thinking" while the evaluator runs. It exists only while the backend reports work in progress, so it is the answer to "is anything coming?". */
export default function CompanionWorkingRow({ evaluating, investigating, question, onStop }: CompanionWorkingRowProps) {
  const researching = investigating > 0;
  if (!researching && !evaluating) return null;
  const label = researching
    ? `${investigating === 1 ? 'Researching' : `Researching ${investigating} questions`}${question ? `: ${question}` : ''}`
    : 'Thinking…';
  return (
    <div className={`companion-working-row${researching ? ' is-researching' : ''}`} role="status">
      <span className="meeting-connection-indicator meeting-connection-indicator--ready companion-working-dot" aria-hidden="true" />
      <span className="meeting-status-message companion-working-label">{label}</span>
      {researching && (
        <button type="button" className="meeting-history-load-more-button" onClick={() => void onStop()}>Stop</button>
      )}
    </div>
  );
}
