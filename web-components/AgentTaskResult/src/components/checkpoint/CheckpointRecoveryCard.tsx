import { useCallback, useEffect, useRef, useState } from 'react';
import { hydrateAgentFromBackend } from '../../app/agents/agentHydration';
import { agentStore } from '../../store/agentStore';
import { checkpointPromptSummary } from './CheckpointFlow';
import { ContinueCircleIcon } from '@shared/windowChrome/CircleControlIcons';
import { DecisionButton } from '../interaction/DecisionButton';

interface Props {
  agentTaskId: string;
  /** The waiting question's text from the timeline, when the timeline has it. */
  prompt?: string;
  /** Changes when a different question starts waiting, which starts a fresh load. */
  questionKey: string;
}

type Phase = 'loading' | 'ready' | 'gone';

/**
 * Shown when the run is waiting for an answer but this window holds no question to show, so the task never looks stuck with nothing to click. It asks the backend for the question as soon as it appears, and "Answer now" asks again. When the question arrives the answer card opens and this card goes away; when the backend says the run is no longer waiting, this card goes away too.
 */
export default function CheckpointRecoveryCard({ agentTaskId, prompt, questionKey }: Props) {
  const [phase, setPhase] = useState<Phase>('loading');
  const mounted = useRef(true);
  const requestCount = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const load = useCallback(async () => {
    const request = requestCount.current + 1;
    requestCount.current = request;
    setPhase('loading');
    let outcome: Awaited<ReturnType<typeof hydrateAgentFromBackend>> | 'failed' = 'failed';
    try {
      outcome = await hydrateAgentFromBackend(agentTaskId);
    } catch (error) {
      console.warn('[AgentTaskResult] Could not load the waiting question', { agentTaskId, error });
    }
    if (!mounted.current || requestCount.current !== request) return;
    const agent = agentStore.getAgent(agentTaskId);
    // Once the question is in the store the answer card takes over and this card is unmounted by its parent.
    if (agent?.currentCheckpoint) return;
    // A confirmed read that left the run no longer waiting means there is nothing to answer.
    const confirmedNotWaiting = outcome === 'hydrated' && agent?.status !== 'awaitingInput';
    setPhase(confirmedNotWaiting ? 'gone' : 'ready');
  }, [agentTaskId]);

  useEffect(() => {
    void load();
  }, [load, questionKey]);

  if (phase === 'gone') return null;

  const summary = prompt ? checkpointPromptSummary(prompt) : undefined;
  const loading = phase === 'loading';

  return (
    <section className="checkpoint-reopen-card checkpoint-recovery-card" role="region" aria-labelledby="checkpoint-recovery-eyebrow">
      <div className="agent-task-input-dock">
        <div className="agent-task-input-dock-text">
          <div id="checkpoint-recovery-eyebrow" className="agent-task-input-eyebrow agent-task-input-dock-eyebrow">
            Input required
          </div>
          <div className="agent-task-input-dock-summary">
            {summary || (loading ? 'Loading the question Basil asked…' : 'Basil is waiting for your answer.')}
          </div>
        </div>
        <DecisionButton
          tone="primary"
          icon={<ContinueCircleIcon />}
          label={loading ? 'Loading…' : 'Answer now'}
          onClick={() => void load()}
          disabled={loading}
          className="agent-task-input-dock-action"
          title="load the question so you can answer"
        />
      </div>
    </section>
  );
}
