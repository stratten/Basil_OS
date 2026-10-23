import { PlayCircleIcon } from '../components/MeetingIcons';
import { MeetingMarkdown } from '../lib/markdown';
import type { CompanionStreamEntry } from './companionStreamSelectors';

export const COMPANION_CONTINUE_PROMPT = 'Please continue your previous answer from exactly where it stopped. Do not repeat anything you already wrote.';

type ChatStreamEntry = Extract<CompanionStreamEntry, { type: 'chat' | 'draft' | 'pending' }>;

interface CompanionChatEntryProps {
  entry: ChatStreamEntry;
  /** True only for the newest assistant message when it was cut short and nothing else is in flight. */
  canContinue: boolean;
  busy: boolean;
  onContinue: () => void;
  /** Set when this answer cited nothing and research could still look into it. */
  onLookIntoThis?: (() => void) | null;
}

/** One chat turn in the stream: the reader's question, the Companion's answer, a streaming draft, or the "Thinking" placeholder for an answer that has not started. */
export default function CompanionChatEntry({ entry, canContinue, busy, onContinue, onLookIntoThis = null }: CompanionChatEntryProps) {
  if (entry.type === 'pending') {
    return (
      <div className="companion-chat-message companion-chat-message--assistant is-pending">
        <p>Thinking…</p>
      </div>
    );
  }
  if (entry.type === 'draft') {
    return (
      <div className="companion-chat-message companion-chat-message--assistant is-streaming">
        <MeetingMarkdown content={entry.text} />
      </div>
    );
  }
  const { message } = entry;
  return (
    <div className={`companion-chat-message companion-chat-message--${message.role}${message.status === 'error' ? ' is-error' : ''}`}>
      {message.role === 'assistant' ? <MeetingMarkdown content={message.text} /> : <p>{message.text}</p>}
      {message.status === 'error' && <p className="companion-item-note">That answer could not be completed.</p>}
      {message.truncated && message.status !== 'error' && <p className="companion-item-note">This answer was cut short to fit.</p>}
      {onLookIntoThis !== null && (
        <button type="button" className="meeting-history-load-more-button companion-chat-research" disabled={busy} title="Search your attached files and Basil records for the answer" onClick={onLookIntoThis}>
          Look into this
        </button>
      )}
      {canContinue && (
        <button type="button" className="meeting-record-button companion-chat-continue" disabled={busy} onClick={onContinue}>
          <PlayCircleIcon />
          Continue
        </button>
      )}
    </div>
  );
}
