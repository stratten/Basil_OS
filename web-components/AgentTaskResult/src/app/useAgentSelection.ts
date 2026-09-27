import { useCallback, useRef } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { AgentState, DisplayableAgentTask } from '../types';
import { agentStore } from '../store/agentStore';
import { hydrateAgentFromBackend } from './agentHydration';

interface UseAgentSelectionArgs {
  setViewedDetail: Dispatch<SetStateAction<DisplayableAgentTask | null>>;
  setSelectedScheduledAgentTaskId: Dispatch<SetStateAction<string | null>>;
  setCreateScheduledMode: Dispatch<SetStateAction<boolean>>;
  setScheduledListVersion: Dispatch<SetStateAction<number>>;
  setPendingAgentTaskSelection: Dispatch<SetStateAction<{ agentTaskId: string; epoch: number } | null>>;
  selectedAgent: AgentState | null;
  viewedDetail: DisplayableAgentTask | null;
}

export function useAgentSelection({
  setViewedDetail,
  setSelectedScheduledAgentTaskId,
  setCreateScheduledMode,
  setScheduledListVersion,
  setPendingAgentTaskSelection,
  selectedAgent,
  viewedDetail,
}: UseAgentSelectionArgs) {
  const selectionEpoch = useRef(0);
  const handleViewHistoricalAgentTask = useCallback((detail: DisplayableAgentTask) => {
    agentStore.deselectAgent();
    setPendingAgentTaskSelection(null);
    setSelectedScheduledAgentTaskId(null);
    setCreateScheduledMode(false);
    setViewedDetail(detail);
  }, [setCreateScheduledMode, setPendingAgentTaskSelection, setSelectedScheduledAgentTaskId, setViewedDetail]);

  const handleAgentTaskDeleted = useCallback((deletedAgentTaskId: string) => {
    setPendingAgentTaskSelection(current => current?.agentTaskId === deletedAgentTaskId ? null : current);
    if (
      viewedDetail?.agentTaskId === deletedAgentTaskId ||
      viewedDetail?.rootTaskId === deletedAgentTaskId ||
      viewedDetail?.agentTaskHistory.some(item => item.id === deletedAgentTaskId)
    ) {
      setViewedDetail(null);
      setSelectedScheduledAgentTaskId(null);
      setCreateScheduledMode(false);
    }

    if (
      selectedAgent?.agentTaskId === deletedAgentTaskId ||
      selectedAgent?.rootTaskId === deletedAgentTaskId
    ) {
      agentStore.deselectAgent();
    }
  }, [
    selectedAgent?.agentTaskId,
    selectedAgent?.rootTaskId,
    setCreateScheduledMode,
    setPendingAgentTaskSelection,
    setSelectedScheduledAgentTaskId,
    setViewedDetail,
    viewedDetail?.agentTaskHistory,
    viewedDetail?.agentTaskId,
    viewedDetail?.rootTaskId,
  ]);

  const handleViewScheduledAgentTask = useCallback((scheduledAgentTaskId: string) => {
    agentStore.deselectAgent();
    setPendingAgentTaskSelection(null);
    setViewedDetail(null);
    setCreateScheduledMode(false);
    setSelectedScheduledAgentTaskId(scheduledAgentTaskId);
  }, [setCreateScheduledMode, setPendingAgentTaskSelection, setSelectedScheduledAgentTaskId, setViewedDetail]);

  const handleViewAgentTask = useCallback(async (agentTaskId: string) => {
    const epoch = selectionEpoch.current + 1;
    selectionEpoch.current = epoch;
    const alreadyKnown = !!agentStore.getAgent(agentTaskId);
    if (!alreadyKnown) {
      agentStore.registerAgent(agentTaskId);
      // Tentative starting state — the hydrate call below will replace
      // it with the backend's actual status.
      agentStore.updateStatus(agentTaskId, 'processing');
      setSelectedScheduledAgentTaskId(null);
      setCreateScheduledMode(false);
      setPendingAgentTaskSelection({ agentTaskId, epoch });
      let outcome = await hydrateAgentFromBackend(agentTaskId);
      if (selectionEpoch.current !== epoch) return;
      if (outcome === 'superseded') {
        outcome = await hydrateAgentFromBackend(agentTaskId);
        if (selectionEpoch.current !== epoch) return;
      }
      const hydratedAgent = agentStore.getAgent(agentTaskId);
      const hasDurableLocalProgress = Boolean(
        hydratedAgent
        && (
          hydratedAgent.currentStep
          || (hydratedAgent.progressSteps?.length ?? 0) > 0
          || (hydratedAgent.executionTimeline?.length ?? 0) > 0
          || (hydratedAgent.stepDetails?.length ?? 0) > 0
        ),
      );
      if (outcome === 'hydrated' || (outcome === 'retrying' && hasDurableLocalProgress)) {
        setViewedDetail(null);
        agentStore.selectAgent(agentTaskId);
      }
      setPendingAgentTaskSelection(current => current?.epoch === epoch ? null : current);
      return;
    }
    setViewedDetail(null);
    setPendingAgentTaskSelection(null);
    setSelectedScheduledAgentTaskId(null);
    setCreateScheduledMode(false);
    agentStore.selectAgent(agentTaskId);
    void hydrateAgentFromBackend(agentTaskId);
  }, [
    setCreateScheduledMode,
    setPendingAgentTaskSelection,
    setSelectedScheduledAgentTaskId,
    setViewedDetail,
  ]);

  const handleCreateScheduledAgentTask = useCallback(() => {
    agentStore.deselectAgent();
    setPendingAgentTaskSelection(null);
    setViewedDetail(null);
    setSelectedScheduledAgentTaskId(null);
    setCreateScheduledMode(true);
  }, [setCreateScheduledMode, setPendingAgentTaskSelection, setSelectedScheduledAgentTaskId, setViewedDetail]);

  const handleScheduledAgentTaskSaved = useCallback(() => {
    setCreateScheduledMode(false);
    setSelectedScheduledAgentTaskId(null);
    setScheduledListVersion(version => version + 1);
  }, [setCreateScheduledMode, setScheduledListVersion, setSelectedScheduledAgentTaskId]);

  const handleScheduledAgentTaskDeleted = useCallback(() => {
    setSelectedScheduledAgentTaskId(null);
    setCreateScheduledMode(false);
    setScheduledListVersion(version => version + 1);
  }, [setCreateScheduledMode, setScheduledListVersion, setSelectedScheduledAgentTaskId]);

  const handleScheduledRunSelected = useCallback((agentTaskId: string) => {
    handleViewAgentTask(agentTaskId);
  }, [handleViewAgentTask]);

  return {
    handleViewHistoricalAgentTask,
    handleAgentTaskDeleted,
    handleViewScheduledAgentTask,
    handleViewAgentTask,
    handleCreateScheduledAgentTask,
    handleScheduledAgentTaskSaved,
    handleScheduledAgentTaskDeleted,
    handleScheduledRunSelected,
  };
}

