import { ContinueCircleIcon, StopCircleIcon } from '@shared/CircleControlIcons';
import { DecisionActions, DecisionButton } from '../interaction/DecisionButton';

interface Props {
  /** The count of approvals waiting, so the bar says what it holds. */
  count: number;
  /** One line describing what is waiting, such as the first line of the command. */
  summary: string;
  /** Returns from the docked bar to the full approval. */
  onRestore: () => void;
  /** Ends the whole task, the same action as the header Stop. */
  onStopTask?: () => void;
  isStopping?: boolean;
}

/** The slim bar an approval collapses to while the user looks over the work behind it. The full approval stays mounted and hidden beside it, so a typed note and the Remember tick survive the round trip. */
export default function ApprovalDock({ count, summary, onRestore, onStopTask, isStopping = false }: Props) {
  const eyebrow = count > 1 ? `${count} approvals required` : 'Approval required';
  return (
    <section
      className="approval-dock"
      role="region"
      aria-labelledby="approval-dock-eyebrow"
      data-agent-desk-interactive-overlay="true"
      data-preferred-content-width={720}
    >
      <div className="approval-dock__text">
        <div id="approval-dock-eyebrow" className="approval-dock__eyebrow">{eyebrow}</div>
        {summary && <div className="approval-dock__summary">{summary}</div>}
      </div>
      <DecisionActions className="approval-dock__actions">
        {onStopTask && (
          <DecisionButton
            tone="neutral"
            icon={<StopCircleIcon />}
            label={isStopping ? 'Stopping' : 'Stop task'}
            onClick={onStopTask}
            disabled={isStopping}
            title="ends the whole task, the same as Stop in the header"
          />
        )}
        <DecisionButton tone="primary" icon={<ContinueCircleIcon />} label="Review now" onClick={onRestore} title="bring the approval back so you can decide" />
      </DecisionActions>
    </section>
  );
}
