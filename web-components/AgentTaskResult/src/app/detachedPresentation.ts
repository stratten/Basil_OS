import type { DisplayableAgentTask } from '../types';

export function effectiveRootId(task: Pick<DisplayableAgentTask, 'agentTaskId' | 'rootTaskId'>): string {
  return task.rootTaskId || task.agentTaskId;
}

export function isDisplaySourceDetached(
  task: DisplayableAgentTask | null,
  detachedRoots: Set<string>,
): boolean {
  return task !== null && detachedRoots.has(effectiveRootId(task));
}
