import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';

export type RunPauseState = 'running' | 'paused';

interface PauseControlAgent {
  agentTaskId: string;
  rootTaskId?: string;
  status: string;
}

export interface RunPauseControl {
  /** What the header's pause control offers. `undefined` while nothing is running or paused, such as a run parked on a question or a finished one. */
  state: RunPauseState | undefined;
  /** A pause was accepted and takes effect after the current step. */
  isPausing: boolean;
  pause: () => void;
  resume: () => void;
}

export function runPauseStateForStatus(status: string | undefined): RunPauseState | undefined {
  if (status === 'paused') return 'paused';
  if (status === 'processing' || status === 'routing' || status === 'capturing') return 'running';
  return undefined;
}

/** Pause and resume for the task the window shows, the same two calls the note box makes, without a note. */
export function useRunPauseControl(selectedAgent: PauseControlAgent | null | undefined): RunPauseControl {
  const rootTaskId = selectedAgent ? selectedAgent.rootTaskId || selectedAgent.agentTaskId : undefined;
  const state = runPauseStateForStatus(selectedAgent?.status);
  const [isPausing, setIsPausing] = useState(false);
  const inFlight = useRef(false);

  // A new task, or a change between running and paused, ends any wait for a pause.
  useEffect(() => {
    setIsPausing(false);
    inFlight.current = false;
  }, [rootTaskId, state]);

  const pause = useCallback(() => {
    if (!rootTaskId || inFlight.current) return;
    inFlight.current = true;
    const turnTaskId = agentStore.getCurrentTurnTaskId(rootTaskId);
    api.pauseSession(turnTaskId)
      .then(() => setIsPausing(true))
      .catch(error => console.error('[App] Pause failed:', error))
      .finally(() => { inFlight.current = false; });
  }, [rootTaskId]);

  const resume = useCallback(() => {
    if (!rootTaskId || inFlight.current) return;
    inFlight.current = true;
    const turnTaskId = agentStore.getCurrentTurnTaskId(rootTaskId);
    api.resumeSession(turnTaskId)
      .catch(error => console.error('[App] Resume failed:', error))
      .finally(() => { inFlight.current = false; });
  }, [rootTaskId]);

  return { state, isPausing, pause, resume };
}
