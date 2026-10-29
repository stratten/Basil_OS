import type { WSEvent } from '../types';

export class DetachedAgentTaskScope {
  private readonly knownTaskIds = new Set<string>();

  constructor(readonly rootTaskId: string) {
    this.knownTaskIds.add(rootTaskId);
  }

  admits(event: WSEvent): boolean {
    const agentTaskId = event.agent_task_id;
    if (!agentTaskId) return false;

    const rootTaskId = event.root_task_id as string | undefined;
    const previousTaskId = event.previous_task_id as string | undefined;
    const isKnown = this.knownTaskIds.has(agentTaskId);
    const belongsToRoot = agentTaskId === this.rootTaskId || rootTaskId === this.rootTaskId;
    const extendsKnownChain = !!previousTaskId && this.knownTaskIds.has(previousTaskId);

    if (!isKnown && !belongsToRoot && !extendsKnownChain) {
      return false;
    }

    this.knownTaskIds.add(agentTaskId);
    return true;
  }
}
