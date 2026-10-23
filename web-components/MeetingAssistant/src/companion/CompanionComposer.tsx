import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import NativeSymbolIcon from '../../../shared/NativeSymbolIcon';
import ExecutionDisclosureChevron from '../../../shared/ExecutionDisclosureChevron';
import CollapsibleRegion from '../../../shared/CollapsibleRegion';

export const COMPANION_CHAT_MAX_CHARS = 4000;

interface CompanionComposerProps {
  canSend: boolean;
  disabledMessage: string;
  /** Resolves true when the backend accepted the message, so the text is cleared only then. */
  onSend: (text: string) => Promise<boolean>;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  /** What to flag on the collapsed bar ("Answering…", "2 new"), or null when nothing is waiting. */
  attentionLabel: string | null;
  /** Sends are in flight elsewhere (the Continue button), so a second one must wait. */
  busy: boolean;
}

/** The bottom input bar. Collapsed it is a one-line "Ask the Companion" bar that keeps the draft and shows when something is waiting; focusing or clicking it opens it again. Collapsing is the reader's way to reclaim the space as a long meeting fills the stream. */
export default function CompanionComposer({ canSend, disabledMessage, onSend, collapsed, onCollapsedChange, attentionLabel, busy }: CompanionComposerProps) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const wasCollapsed = useRef(collapsed);

  useEffect(() => {
    if (wasCollapsed.current && !collapsed) inputRef.current?.focus();
    wasCollapsed.current = collapsed;
  }, [collapsed]);

  const submit = async () => {
    const trimmed = text.trim();
    if (trimmed === '' || sending || busy || !canSend) return;
    setSending(true);
    const accepted = await onSend(trimmed);
    setSending(false);
    if (accepted) setText('');
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  };

  if (!canSend) {
    return (
      <section className="companion-composer" aria-label="Ask the Companion">
        <p className="companion-state-note">{disabledMessage}</p>
      </section>
    );
  }

  const draftPreview = text.trim();
  return (
    <section className={`companion-composer${collapsed ? ' is-collapsed' : ''}`} aria-label="Ask the Companion">
      <button
        type="button"
        className="companion-composer-bar"
        aria-expanded={!collapsed}
        aria-label={collapsed ? 'Open the question box' : 'Collapse the question box'}
        onClick={() => onCollapsedChange(!collapsed)}
      >
        <ExecutionDisclosureChevron expanded={!collapsed} />
        <span className="companion-composer-title">Ask the Companion</span>
        {collapsed && draftPreview !== '' && <span className="companion-composer-draft">Draft: {draftPreview}</span>}
        {collapsed && attentionLabel !== null && <span className="companion-composer-attention">{attentionLabel}</span>}
      </button>
      <CollapsibleRegion expanded={!collapsed}>
        <form
          className="companion-chat-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <textarea
            ref={inputRef}
            className="meeting-analysis-custom-instructions companion-chat-input"
            aria-label="Message to the Companion"
            placeholder={'Ask a question, or say "when pricing comes up, give me last quarter\'s numbers".'}
            value={text}
            maxLength={COMPANION_CHAT_MAX_CHARS}
            rows={2}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            type="submit"
            className="meeting-record-button companion-chat-send"
            aria-label={sending ? 'Sending…' : 'Send'}
            title={sending ? 'Sending…' : 'Send (Enter)'}
            disabled={sending || busy || text.trim() === ''}
          >
            <NativeSymbolIcon name="send" />
          </button>
        </form>
      </CollapsibleRegion>
    </section>
  );
}
