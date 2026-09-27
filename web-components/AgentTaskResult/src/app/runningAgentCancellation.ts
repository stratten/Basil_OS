import { cancelSession } from '../services/api';
import { reportAgentTaskCancellationStage } from '../services/bridge';

export interface RunningAgentCancellationStore {
  isTransientWithoutDurableData: (agentTaskId: string) => boolean;
  markCancelling: (agentTaskId: string) => void;
  markCancellationUnconfirmed: (agentTaskId: string, message: string) => void;
  removeAgent: (agentTaskId: string) => void;
  getAgent: (agentTaskId: string) => { isCancelling?: boolean; isCancelled?: boolean } | undefined;
}

type CancellationRequest = (agentTaskId: string, reason?: string) => Promise<unknown>;

const activeAttempts = new Map<string, symbol>();

export function beginRunningAgentCancellation(
  store: RunningAgentCancellationStore,
  rootTaskId: string,
  executionTaskId: string,
  notifyHost: (agentTaskId: string) => void,
  requestCancellation: CancellationRequest = cancelSession,
): boolean {
  const attempt = Symbol(executionTaskId);
  activeAttempts.set(rootTaskId, attempt);
  const isProvisional = store.isTransientWithoutDurableData(rootTaskId);
  store.markCancelling(rootTaskId);
  reportCancellationStage(executionTaskId, 'clicked');

  if (isProvisional) {
    store.removeAgent(rootTaskId);
  }

  let nativeFallbackSent = false;
  const sendNativeFallback = () => {
    if (nativeFallbackSent) return;
    nativeFallbackSent = true;
    reportCancellationStage(executionTaskId, 'native_fallback');
    try {
      notifyHost(executionTaskId);
    } catch (error) {
      console.error('[Cancellation] Native fallback dispatch failed:', error);
    }
  };

  const fallbackTimer = globalThis.setTimeout(sendNativeFallback, 350);
  void requestCancellation(executionTaskId, 'User requested cancellation')
    .then(() => {
      globalThis.clearTimeout(fallbackTimer);
      reportCancellationStage(executionTaskId, 'rest_acknowledged');
    })
    .catch((error) => {
      globalThis.clearTimeout(fallbackTimer);
      reportCancellationStage(executionTaskId, 'rest_failed');
      console.error('[Cancellation] REST cancellation failed:', error);
      sendNativeFallback();
    });

  globalThis.setTimeout(() => {
    if (activeAttempts.get(rootTaskId) !== attempt) return;
    activeAttempts.delete(rootTaskId);
    const agent = store.getAgent(rootTaskId);
    if (!agent?.isCancelling || agent.isCancelled) {
      reportCancellationStage(executionTaskId, 'terminal_confirmed');
      return;
    }
    reportCancellationStage(executionTaskId, 'confirmation_timeout');
    store.markCancellationUnconfirmed(rootTaskId, 'Stop has not been confirmed');
  }, 5000);

  return isProvisional;
}

function reportCancellationStage(agentTaskId: string, stage: string): void {
  try {
    reportAgentTaskCancellationStage(agentTaskId, stage);
  } catch (error) {
    console.error('[Cancellation] Diagnostic bridge failed:', error);
  }
}
