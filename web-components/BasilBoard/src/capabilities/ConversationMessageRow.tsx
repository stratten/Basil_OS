import { memo, useState } from 'react';
import {
  CheckmarkIcon,
  MarkdownCopyIcon,
  RichTextCopyIcon,
} from '@agent-task/components/result/CopyButtons';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import type { ConversationMessageItem } from '../contracts';
import HomeMarkdown from '../home/HomeMarkdown';
import AgentTaskStatusCard from './AgentTaskStatusCard';
import {
  conversationAttachments,
  conversationDisplayMarkdown,
  formatConversationTimestamp,
} from './chatsPresentation';
import { shouldShowAgentTaskStatusCard } from './conversationAgentStatusPresentation';

export interface ConversationMessageRowProps {
  message: ConversationMessageItem;
  modelDisplayNames: ReadonlyMap<string, string>;
  copiedFormat?: 'markdown' | 'richText';
  onCopy: (messageId: string, content: string, format: 'markdown' | 'richText') => void;
  onPreviewArtifact: (agentTaskId: string, artifactId: string) => void;
  onViewAllArtifacts: (agentTaskId: string) => void;
}

function ConversationMessageRowComponent({
  message,
  modelDisplayNames,
  copiedFormat,
  onCopy,
  onPreviewArtifact,
  onViewAllArtifacts,
}: ConversationMessageRowProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const isUser = message.role === 'user';
  const isLoading = message.metadata.loading === true;
  const isStreaming = message.metadata.streaming === true;
  const isCancelled = message.metadata.cancelled === true;
  const thinking = typeof message.metadata.thinking === 'string' ? message.metadata.thinking : '';
  const answeredByFallbackModel = typeof message.metadata.answered_by_fallback_model === 'string'
    ? message.metadata.answered_by_fallback_model
    : '';
  const attachments = conversationAttachments(message);
  const showAgentTaskCard = !isUser && shouldShowAgentTaskStatusCard(message);

  return (
    <article
      className={`chats-message chats-message-${isUser ? 'user' : 'assistant'}`}
      aria-label={`${isUser ? 'You' : 'Basil'} at ${formatConversationTimestamp(message.timestamp)}`}
    >
      {!isUser ? <span className="chats-message-icon" aria-hidden="true">B</span> : null}
      <div className="chats-message-column">
        {thinking ? (
          <div className="chats-thinking">
            <button
              type="button"
              className="chats-thinking-toggle"
              aria-expanded={thinkingExpanded}
              onClick={() => setThinkingExpanded((prev) => !prev)}
            >
              <span className="chats-thinking-chevron" aria-hidden="true">
                <ExecutionDisclosureChevron expanded={thinkingExpanded} color="var(--secondary, #33559b)" />
              </span>
              <span>{isStreaming ? 'Thinking...' : 'View thinking'}</span>
            </button>
            {thinkingExpanded ? <p>{thinking}</p> : null}
          </div>
        ) : null}
        {showAgentTaskCard ? (
          <AgentTaskStatusCard
            message={message}
            onPreviewArtifact={onPreviewArtifact}
            onViewAllArtifacts={onViewAllArtifacts}
          />
        ) : null}
        {!showAgentTaskCard || isLoading || message.content.trim() ? (
          <div className="chats-message-bubble">
            {isLoading ? (
              <span className="chats-thinking-placeholder" role="status" aria-label="Thinking">
                <span className="chats-pulsing-dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
                Thinking
              </span>
            ) : isCancelled && !message.content.trim() ? (
              <span>Response cancelled before content was generated.</span>
            ) : (
              <HomeMarkdown
                content={isUser ? conversationDisplayMarkdown(message) : message.content}
                variant={isUser ? 'user' : 'assistant'}
              />
            )}
          </div>
        ) : null}
        {attachments.length > 0 ? (
          <div className="chats-attachments" aria-label="Attachments">
            {attachments.map((file) => (
              <span key={`${message.id}-${file.path}`} title={file.path}>
                {file.filename}
              </span>
            ))}
          </div>
        ) : null}
        <div className="chats-message-footer">
          <time dateTime={message.timestamp}>
            {formatConversationTimestamp(message.timestamp)}
            {!isUser && message.model_id ? ` · ${modelDisplayNames.get(message.model_id) ?? message.model_id}` : ''}
          </time>
          {isCancelled ? <span className="chats-cancelled-label">Cancelled</span> : null}
          {answeredByFallbackModel ? (
            <span className="chats-cancelled-label" title={`Preferred model was unreachable; answered by local fallback: ${answeredByFallbackModel}`}>
              Answered with local fallback
            </span>
          ) : null}
          {!isUser && !isLoading && message.content.trim() ? (
            <span className="chats-copy-actions">
              {(['richText', 'markdown'] as const).map((format) => {
                const copied = copiedFormat === format;
                const label = format === 'richText' ? 'Copy rich text' : 'Copy Markdown';
                return (
                  <button
                    key={format}
                    type="button"
                    onClick={() => onCopy(message.id, message.content, format)}
                    aria-label={copied ? `${label} copied` : label}
                    title={copied ? 'Copied' : label}
                  >
                    {copied ? <CheckmarkIcon /> : (
                      format === 'richText' ? <RichTextCopyIcon /> : <MarkdownCopyIcon />
                    )}
                  </button>
                );
              })}
              <span className="sr-only" aria-live="polite">
                {copiedFormat ? 'Copied to clipboard.' : ''}
              </span>
            </span>
          ) : null}
        </div>
      </div>
      {isUser ? (
        <span className="chats-message-icon chats-person-icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" focusable="false">
            <circle cx="10" cy="7" r="3" />
            <path d="M4.5 17c.5-3.3 2.4-5 5.5-5s5 1.7 5.5 5" />
          </svg>
        </span>
      ) : null}
    </article>
  );
}

export default memo(ConversationMessageRowComponent);
