import { agentStore } from '../../store/agentStore';
import type { CheckpointData } from '../../types';
import { checkpointPromptSummary } from './CheckpointFlow';
import { ContinueCircleIcon } from '@shared/windowChrome/CircleControlIcons';
import { DecisionButton } from '../interaction/DecisionButton';

interface Props {
  agentTaskId: string;
  checkpoint: CheckpointData;
}

/** Shown after the user skips a question the backend is still waiting on, so the task never looks stuck with no way to answer it. */
export default function CheckpointReopenCard({ agentTaskId, checkpoint }: Props) {
  const summary = checkpointPromptSummary(checkpoint.prompt);
  return (
    <section className="checkpoint-reopen-card" role="region" aria-labelledby="checkpoint-reopen-eyebrow">
      <div className="agent-task-input-dock">
        <div className="agent-task-input-dock-text">
          <div id="checkpoint-reopen-eyebrow" className="agent-task-input-eyebrow agent-task-input-dock-eyebrow">
            Input required
          </div>
          {summary && <div className="agent-task-input-dock-summary">{summary}</div>}
        </div>
        <DecisionButton
          tone="primary"
          icon={<ContinueCircleIcon />}
          label="Answer now"
          onClick={() => agentStore.showCheckpoint(agentTaskId, checkpoint)}
          className="agent-task-input-dock-action"
          title="bring the question back so you can answer"
        />
      </div>
    </section>
  );
}
