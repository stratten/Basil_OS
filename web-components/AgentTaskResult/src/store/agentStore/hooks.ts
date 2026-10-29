import { useCallback, useSyncExternalStore } from 'react';

import type { AgentState } from '../../types';
import { agentStore } from './singleton';

export function useAgentStore(): number {
  return useSyncExternalStore(
    cb => agentStore.subscribe(cb),
    () => agentStore.getSnapshot()
  );
}

export function useSelectedAgent(): AgentState | undefined {
  const selectedAgentId = useSyncExternalStore(
    cb => agentStore.subscribe(cb),
    () => agentStore.getSelectedAgentId()
  );
  useSyncExternalStore(
    cb => selectedAgentId ? agentStore.subscribeToAgent(selectedAgentId, cb) : () => {},
    () => selectedAgentId ? agentStore.getAgentVersion(selectedAgentId) : 0
  );
  return selectedAgentId ? agentStore.getAgent(selectedAgentId) : undefined;
}

export function useAgent(agentTaskId: string): AgentState | undefined {
  useSyncExternalStore(
    cb => agentStore.subscribeToAgent(agentTaskId, cb),
    () => agentStore.getAgentVersion(agentTaskId)
  );
  return agentStore.getAgent(agentTaskId);
}

export function useActiveAgents(): AgentState[] {
  useAgentStore();
  return agentStore.getActiveAgents();
}

export function useAllAgents(): AgentState[] {
  useAgentStore();
  return agentStore.getAllAgents();
}

export function useSelectAgent(): (agentTaskId: string) => void {
  return useCallback((agentTaskId: string) => {
    agentStore.selectAgent(agentTaskId);
  }, []);
}
