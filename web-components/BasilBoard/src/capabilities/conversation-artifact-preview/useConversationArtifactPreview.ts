import { useCallback, useEffect, useState } from 'react';
import { createBoardArtifactPreviewTransport } from '../../services/artifactPreviewBridge';
import {
  clearConversationArtifact,
  isSelectionForConversation,
  isSameConversationArtifactSelection,
  selectConversationArtifact,
  selectFirstConversationArtifact,
  type ConversationArtifactPreviewSelection,
} from './conversationArtifactPreviewState';

export interface UseConversationArtifactPreviewOptions {
  selectedConversationId?: string;
}

export function useConversationArtifactPreview({
  selectedConversationId,
}: UseConversationArtifactPreviewOptions) {
  const [selection, setSelection] = useState<ConversationArtifactPreviewSelection>();
  const [transport] = useState(() => createBoardArtifactPreviewTransport());

  useEffect(() => {
    setSelection((current) => (
      current && !isSelectionForConversation(current, selectedConversationId)
        ? clearConversationArtifact()
        : current
    ));
  }, [selectedConversationId]);

  const onPreviewArtifact = useCallback((agentTaskId: string, artifactId: string) => {
    if (!selectedConversationId) return;
    const nextSelection = selectConversationArtifact(selectedConversationId, agentTaskId, artifactId);
    if (!nextSelection) return;
    setSelection((current) => (
      isSameConversationArtifactSelection(current, nextSelection) ? current : nextSelection
    ));
  }, [selectedConversationId]);

  const onViewAllArtifacts = useCallback((agentTaskId: string) => {
    if (!selectedConversationId) return;
    const nextSelection = selectFirstConversationArtifact(selectedConversationId, agentTaskId);
    if (!nextSelection) return;
    setSelection((current) => (
      isSameConversationArtifactSelection(current, nextSelection) ? current : nextSelection
    ));
  }, [selectedConversationId]);

  const onSelectArtifact = useCallback((artifactId: string) => {
    setSelection((current) => {
      if (!current) return current;
      const nextSelection = selectConversationArtifact(current.conversationId, current.agentTaskId, artifactId);
      if (!nextSelection) return current;
      return isSameConversationArtifactSelection(current, nextSelection) ? current : nextSelection;
    });
  }, []);

  const onCloseSidebar = useCallback(() => {
    setSelection(clearConversationArtifact());
  }, []);

  return {
    selection,
    transport,
    onPreviewArtifact,
    onViewAllArtifacts,
    onSelectArtifact,
    onCloseSidebar,
  };
}
