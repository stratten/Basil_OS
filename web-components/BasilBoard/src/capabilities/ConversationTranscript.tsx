import { memo, useCallback, type RefObject, type UIEvent } from 'react';
import { useCopyFeedback } from '@shared/useCopyFeedback';
import type { ConversationMessageItem } from '../contracts';
import ConversationMessageRow from './ConversationMessageRow';

const EMPTY_MODEL_DISPLAY_NAMES: ReadonlyMap<string, string> = new Map();

interface ConversationTranscriptProps {
  viewportRef: RefObject<HTMLDivElement>;
  messages: ConversationMessageItem[];
  loading: boolean;
  loadError?: string;
  selectedId?: string;
  modelDisplayNames?: ReadonlyMap<string, string>;
  onRetryLoad: () => void;
  onPinnedChange: (pinned: boolean) => void;
  onCopy: (content: string, format: 'markdown' | 'richText') => Promise<void>;
  onPreviewArtifact: (agentTaskId: string, artifactId: string) => void;
  onViewAllArtifacts: (agentTaskId: string) => void;
}

function ConversationTranscriptComponent({
  viewportRef,
  messages,
  loading,
  loadError,
  selectedId,
  modelDisplayNames = EMPTY_MODEL_DISPLAY_NAMES,
  onRetryLoad,
  onPinnedChange,
  onCopy,
  onPreviewArtifact,
  onViewAllArtifacts,
}: ConversationTranscriptProps) {
  const { copiedKey: copiedAction, flash: flashCopiedAction } = useCopyFeedback<string>();

  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const target = event.currentTarget;
    onPinnedChange(
      target.scrollHeight - target.scrollTop - target.clientHeight <= 80,
    );
  };
  const copyMessage = useCallback(async (
    messageId: string,
    content: string,
    format: 'markdown' | 'richText',
  ) => {
    const actionId = `${messageId}:${format}`;
    await onCopy(content, format);
    flashCopiedAction(actionId);
  }, [onCopy, flashCopiedAction]);

  const handleRowCopy = useCallback((messageId: string, content: string, format: 'markdown' | 'richText') => {
    void copyMessage(messageId, content, format).catch(() => undefined);
  }, [copyMessage]);

  return (
    <div
      ref={viewportRef}
      className="chats-message-viewport"
      onScroll={handleScroll}
    >
      {loading ? (
        <div className="chats-message-state" role="status">Loading messages...</div>
      ) : loadError ? (
        <div className="chats-message-state chats-error" role="alert">
          <span>{loadError}</span>
          {selectedId ? <button type="button" onClick={onRetryLoad}>Retry</button> : null}
        </div>
      ) : messages.length === 0 ? (
        <div className="chats-message-state">Start the conversation below.</div>
      ) : (
        <div className="chats-message-list" aria-live="polite">
          {messages.map((message) => {
            const copiedFormat = copiedAction?.startsWith(`${message.id}:`)
              ? (copiedAction.slice(message.id.length + 1) as 'markdown' | 'richText')
              : undefined;
            return (
              <ConversationMessageRow
                key={message.id}
                message={message}
                modelDisplayNames={modelDisplayNames}
                copiedFormat={copiedFormat}
                onCopy={handleRowCopy}
                onPreviewArtifact={onPreviewArtifact}
                onViewAllArtifacts={onViewAllArtifacts}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

export default memo(ConversationTranscriptComponent);
