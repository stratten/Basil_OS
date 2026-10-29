import { describe, expect, it } from 'vitest';
import {
  clearConversationArtifact,
  isSelectionForConversation,
  isSameConversationArtifactSelection,
  selectConversationArtifact,
  selectFirstConversationArtifact,
} from './conversationArtifactPreviewState';

describe('conversationArtifactPreviewState', () => {
  it('selectConversationArtifact captures the conversation, task, and artifact identity', () => {
    expect(selectConversationArtifact('conv-1', 'task-1', 'artifact-1')).toEqual({
      conversationId: 'conv-1',
      agentTaskId: 'task-1',
      artifactId: 'artifact-1',
    });
  });

  it('selectFirstConversationArtifact omits artifactId so the sidebar picks the first eligible document', () => {
    expect(selectFirstConversationArtifact('conv-1', 'task-1')).toEqual({
      conversationId: 'conv-1',
      agentTaskId: 'task-1',
      artifactId: undefined,
    });
  });

  it('clearConversationArtifact returns undefined', () => {
    expect(clearConversationArtifact()).toBeUndefined();
  });

  it('isSelectionForConversation matches only the same conversation ID', () => {
    const selection = selectConversationArtifact('conv-1', 'task-1', 'artifact-1');
    expect(isSelectionForConversation(selection, 'conv-1')).toBe(true);
    expect(isSelectionForConversation(selection, 'conv-2')).toBe(false);
    expect(isSelectionForConversation(selection, undefined)).toBe(false);
    expect(isSelectionForConversation(undefined, 'conv-1')).toBe(false);
  });

  it('rejects blank identifiers and recognizes an equivalent selection', () => {
    const selection = selectConversationArtifact('conv-1', 'task-1', 'artifact-1');
    expect(selectConversationArtifact(' ', 'task-1', 'artifact-1')).toBeUndefined();
    expect(selectConversationArtifact('conv-1', '', 'artifact-1')).toBeUndefined();
    expect(selectConversationArtifact('conv-1', 'task-1', '   ')).toBeUndefined();
    expect(selectFirstConversationArtifact('', 'task-1')).toBeUndefined();
    expect(selectFirstConversationArtifact('conv-1', ' ')).toBeUndefined();
    expect(isSameConversationArtifactSelection(
      selection,
      selectConversationArtifact('conv-1', 'task-1', 'artifact-1'),
    )).toBe(true);
  });
});
