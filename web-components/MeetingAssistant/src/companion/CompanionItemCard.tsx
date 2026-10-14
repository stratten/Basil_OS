import { memo, useState } from 'react';
import { useCopiedFlag } from '@shared/useCopyFeedback';
import { formatClockSeconds } from '@shared/formatClockSeconds';
import { copyText } from '../bridge/meetingBridge';
import { CheckIcon, CloseIcon, CopyIcon, PinIcon, ThumbDownIcon, ThumbUpIcon } from '../components/MeetingIcons';
import { MeetingMarkdown } from '../lib/markdown';
import type { CompanionFeedbackAction, CompanionItem, FileCitation } from './types';

const KIND_LABELS: Record<CompanionItem['kind'], string> = {
  insight: 'Insight',
  suggestion: 'Suggestion',
  answer: 'Answer',
  context_note: 'From your sources',
};

export function formatItemTime(item: CompanionItem): string {
  return `[${formatClockSeconds(item.transcript_range.start, { padMinutes: true })}]`;
}

export function citationLabel(citation: FileCitation): string {
  return citation.line_start === citation.line_end
    ? `${citation.path}:${citation.line_start}`
    : `${citation.path}:${citation.line_start}-${citation.line_end}`;
}

export function itemCopyText(item: CompanionItem): string {
  if (item.citations.length === 0) return item.text;
  return `${item.text}\n\nSources:\n${item.citations.map((citation) => `- ${citationLabel(citation)}`).join('\n')}`;
}

interface CompanionItemCardProps {
  item: CompanionItem;
  watchTopic: string | null;
  onFeedback: (itemId: string, action: CompanionFeedbackAction) => Promise<boolean>;
}

function CompanionItemCard({ item, watchTopic, onFeedback }: CompanionItemCardProps) {
  const [copied, flashCopied] = useCopiedFlag();
  const [rating, setRating] = useState<'useful' | 'not_useful' | null>(null);

  const rate = (next: 'useful' | 'not_useful') => {
    setRating(next);
    void onFeedback(item.id, next);
  };

  const copy = () => {
    copyText(itemCopyText(item));
    flashCopied();
    void onFeedback(item.id, 'copied');
  };

  return (
    <article className={`companion-item companion-item--${item.kind}${item.pinned ? ' is-pinned' : ''}`} aria-label={`${KIND_LABELS[item.kind]} at ${formatItemTime(item)}`}>
      <header className="companion-item-header">
        <span className="companion-item-kind">{KIND_LABELS[item.kind]}</span>
        {watchTopic !== null && <span className="meeting-status-message">Watch: {watchTopic}</span>}
        <span className="meeting-transcription-state" title="Where this happened in the meeting">{formatItemTime(item)}</span>
      </header>
      <div className="companion-item-body">
        <MeetingMarkdown content={item.text} />
      </div>
      {item.truncated && <p className="companion-item-note">This answer was cut short to fit.</p>}
      {item.no_source && <p className="companion-item-note">Not from your files. Based on the conversation alone.</p>}
      {item.citations.length > 0 && (
        <details className="companion-citations">
          <summary>{item.citations.length === 1 ? '1 source' : `${item.citations.length} sources`}</summary>
          <ul>
            {item.citations.map((citation, index) => (
              <li key={`${citation.path}:${citation.line_start}:${index}`}>
                <code className="companion-citation-path">{citationLabel(citation)}</code>
                {citation.excerpt !== '' && <pre className="companion-citation-excerpt">{citation.excerpt}</pre>}
              </li>
            ))}
          </ul>
        </details>
      )}
      <footer className="companion-item-actions">
        <button type="button" className="meeting-transcript-icon-button" aria-label={item.pinned ? 'Unpin' : 'Pin'} title={item.pinned ? 'Unpin' : 'Pin'} aria-pressed={item.pinned} onClick={() => void onFeedback(item.id, item.pinned ? 'unpinned' : 'pinned')}>
          <PinIcon filled={item.pinned} />
        </button>
        <button type="button" className="meeting-transcript-icon-button" aria-label={copied ? 'Copied' : 'Copy'} title={copied ? 'Copied' : 'Copy'} onClick={copy}>
          {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
        <button type="button" className="meeting-transcript-icon-button" aria-label="Helpful" title="Helpful" aria-pressed={rating === 'useful'} onClick={() => rate('useful')}>
          <ThumbUpIcon filled={rating === 'useful'} />
        </button>
        <button type="button" className="meeting-transcript-icon-button" aria-label="Not helpful" title="Not helpful" aria-pressed={rating === 'not_useful'} onClick={() => rate('not_useful')}>
          <ThumbDownIcon filled={rating === 'not_useful'} />
        </button>
        <button type="button" className="meeting-transcript-icon-button companion-item-dismiss" aria-label="Dismiss" title="Dismiss" onClick={() => void onFeedback(item.id, 'dismissed')}>
          <CloseIcon />
        </button>
      </footer>
    </article>
  );
}

export default memo(CompanionItemCard);
