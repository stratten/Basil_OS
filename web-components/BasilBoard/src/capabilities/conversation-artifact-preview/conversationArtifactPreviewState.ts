export interface ConversationArtifactPreviewSelection {
  conversationId: string;
  agentTaskId: string;
  artifactId?: string;
}

export function selectConversationArtifact(
  conversationId: string,
  agentTaskId: string,
  artifactId: string,
): ConversationArtifactPreviewSelection | undefined {
  if (!isNonBlankText(conversationId) || !isNonBlankText(agentTaskId) || !isNonBlankText(artifactId)) {
    return undefined;
  }
  return { conversationId, agentTaskId, artifactId };
}

export function selectFirstConversationArtifact(
  conversationId: string,
  agentTaskId: string,
): ConversationArtifactPreviewSelection | undefined {
  if (!isNonBlankText(conversationId) || !isNonBlankText(agentTaskId)) {
    return undefined;
  }
  return { conversationId, agentTaskId, artifactId: undefined };
}

export function clearConversationArtifact(): undefined {
  return undefined;
}

export function isSelectionForConversation(
  selection: ConversationArtifactPreviewSelection | undefined,
  conversationId: string | undefined,
): boolean {
  return Boolean(selection && conversationId && selection.conversationId === conversationId);
}

export function isSameConversationArtifactSelection(
  first: ConversationArtifactPreviewSelection | undefined,
  second: ConversationArtifactPreviewSelection | undefined,
): boolean {
  return first?.conversationId === second?.conversationId
    && first?.agentTaskId === second?.agentTaskId
    && first?.artifactId === second?.artifactId;
}

function isNonBlankText(value: string): boolean {
  return value.trim().length > 0;
}
