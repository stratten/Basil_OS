import type { WSEvent } from '../../types';
import {
  buildExternalServiceAccessDetail,
  isExternalServiceAccessFailure,
  isExternalServiceAccessResolved,
  isExternalServiceAccessWaiting,
  requiresUserAttentionForAccess,
} from './blockerEventPresentation';
import { ProgressTimelineAgentStore } from './progressTimelineActions';

export class BlockerEventAgentStore extends ProgressTimelineAgentStore {
  protected handleBlockerWaiting(agentTaskId: string, event: WSEvent) {
    if (isExternalServiceAccessWaiting(event)) {
      const detail = buildExternalServiceAccessDetail(event, 'waiting');
      if (requiresUserAttentionForAccess(event)) {
        this.updateStatus(agentTaskId, 'awaitingInput');
        this.updateProgressStep(agentTaskId, 'Keychain access required', true, false);
        this.clearPendingStepTimer(agentTaskId);
        this.updateAgent(agentTaskId, a => {
          a.currentStep = 'Keychain access required';
          a.showCheckpointPrompt = false;
          a.currentCheckpoint = undefined;
          a.inlineCheckpoint = undefined;
        });
      } else {
        this.updateStatus(agentTaskId, 'processing');
      }
      this.upsertStepDetail(agentTaskId, detail);
      return;
    }

    const message = event.message as string || 'Waiting for access...';
    this.recordVisibleProgressUpdate(agentTaskId, message, true, false);
    this.upsertStepDetail(agentTaskId, {
      id: `blocker_waiting_${Date.now()}`,
      type: 'step',
      timestamp: new Date().toISOString(),
      content: message,
      detail_kind: 'step_note',
      summary: 'Waiting for access',
      body: message,
      metadata: {
        kind: event.kind,
        connection_id: event.connection_id,
      },
      streaming: false,
    });
  }

  protected handleBlockerResolved(agentTaskId: string, event: WSEvent) {
    if (isExternalServiceAccessResolved(event)) {
      if (isExternalServiceAccessFailure(event)) {
        this.recordVisibleProgressUpdate(agentTaskId, 'External service access unavailable', true, false);
        this.upsertStepDetail(agentTaskId, buildExternalServiceAccessDetail(event, 'failed'));
        return;
      }

      const currentStep = this.agents.get(agentTaskId)?.currentStep || '';
      const shouldReplaceAccessStep =
        currentStep === 'Waiting for access...' ||
        currentStep === 'Keychain access required' ||
        currentStep.includes('Waiting for Keychain access');
      this.clearPendingStepTimer(agentTaskId);
      this.updateAgent(agentTaskId, a => {
        a.status = 'processing';
        a.errorMessage = undefined;
        a.isStreaming = false;
        if (shouldReplaceAccessStep) {
          a.currentStep = 'External service access ready. Continuing...';
        }
        a.checkpointAvailable = false;
        a.showCheckpointPrompt = false;
        a.currentCheckpoint = undefined;
        a.inlineCheckpoint = undefined;
      });
      this.upsertStepDetail(agentTaskId, buildExternalServiceAccessDetail(event, 'resolved'));
      return;
    }

    this.recordVisibleProgressUpdate(agentTaskId, event.message as string || 'Access check resolved', true, true);
  }
}
