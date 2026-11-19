/** The one key a conversation is stored under: the id of its first task once a follow-up has recorded it, otherwise the task's own id. Anything kept per conversation, such as a folded note box or a saved draft, must use this so a reader of the task and the run that started from it agree on where it lives. */
export function chainKeyOf(source: { rootTaskId?: string; agentTaskId: string }): string {
  return source.rootTaskId || source.agentTaskId;
}
