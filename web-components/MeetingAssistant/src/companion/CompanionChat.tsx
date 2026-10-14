import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import NativeSymbolIcon from '../../../shared/NativeSymbolIcon';
import { PlayCircleIcon } from '../components/MeetingIcons';
import { MeetingMarkdown } from '../lib/markdown';
import type { ChatMessage } from './types';

export const COMPANION_CHAT_MAX_CHARS = 4000;
export const COMPANION_CONTINUE_PROMPT = 'Please continue your previous answer from exactly where it stopped. Do not repeat anything you already wrote.';

interface CompanionChatProps {
  messages: ChatMessage[];
  drafts: Record<string, string>;
  pendingAssistantIds: string[];
  canSend: boolean;
  disabledMessage: string;
  onSend: (text: string) => Promise<boolean>;
}

export default function CompanionChat({ messages, drafts, pendingAssistantIds, canSend, disabledMessage, onSend }: CompanionChatProps) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const persistedIds = new Set(messages.map((message) => message.id));
  const streaming = Object.entries(drafts).filter(([id]) => !persistedIds.has(id));
  const pending = pendingAssistantIds.filter((id) => !persistedIds.has(id) && !(id in drafts));
  const draftSignature = streaming.map(([id, value]) => `${id}:${value.length}`).join('|');

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages.length, draftSignature, pending.length]);

  const submit = async () => {
    const trimmed = text.trim();
    if (trimmed === '' || sending || !canSend) return;
    setSending(true);
    const accepted = await onSend(trimmed);
    setSending(false);
    if (accepted) setText('');
  };

  const continueAnswer = async () => {
    if (sending || !canSend) return;
    setSending(true);
    await onSend(COMPANION_CONTINUE_PROMPT);
    setSending(false);
  };

  const canContinue = (message: ChatMessage, index: number) =>
    canSend && message.role === 'assistant' && message.truncated && index === messages.length - 1 && streaming.length === 0 && pending.length === 0;

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  };

  const hasHistory = messages.length > 0 || streaming.length > 0 || pending.length > 0;

  return (
    <section className="companion-chat" aria-label="Ask the Companion">
      <h3 className="meeting-section-heading">Ask the Companion</h3>
      {hasHistory && (
        <div className="companion-chat-list" ref={listRef} role="log" aria-live="polite">
          {messages.map((message, index) => (
            <div key={message.id} className={`companion-chat-message companion-chat-message--${message.role}${message.status === 'error' ? ' is-error' : ''}`}>
              {message.role === 'assistant' ? <MeetingMarkdown content={message.text} /> : <p>{message.text}</p>}
              {message.status === 'error' && <p className="companion-item-note">That answer could not be completed.</p>}
              {message.truncated && message.status !== 'error' && <p className="companion-item-note">This answer was cut short to fit.</p>}
              {canContinue(message, index) && (
                <button type="button" className="meeting-record-button companion-chat-continue" disabled={sending} onClick={() => void continueAnswer()}>
                  <PlayCircleIcon />
                  Continue
                </button>
              )}
            </div>
          ))}
          {streaming.map(([id, value]) => (
            <div key={id} className="companion-chat-message companion-chat-message--assistant is-streaming">
              <MeetingMarkdown content={value} />
            </div>
          ))}
          {pending.map((id) => (
            <div key={id} className="companion-chat-message companion-chat-message--assistant is-pending">
              <p>Thinking…</p>
            </div>
          ))}
        </div>
      )}
      {canSend ? (
        <form
          className="companion-chat-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <textarea
            className="meeting-analysis-custom-instructions companion-chat-input"
            aria-label="Message to the Companion"
            placeholder={'Ask a question, or say "when pricing comes up, give me last quarter\'s numbers".'}
            value={text}
            maxLength={COMPANION_CHAT_MAX_CHARS}
            rows={2}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button type="submit" className="meeting-record-button" disabled={sending || text.trim() === ''}>
            <NativeSymbolIcon name="send" />
            {sending ? 'Sending…' : 'Send'}
          </button>
        </form>
      ) : (
        <p className="companion-state-note">{disabledMessage}</p>
      )}
    </section>
  );
}
