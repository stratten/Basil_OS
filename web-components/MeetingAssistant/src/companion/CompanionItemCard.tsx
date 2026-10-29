import { memo, useState } from 'react';
import { useCopiedFlag } from '@shared/useCopyFeedback';
import { formatClockSeconds } from '@shared/formatClockSeconds';
import ExecutionDisclosureChevron from '../../../shared/ExecutionDisclosureChevron';
import { plainMarkdownText } from '../../../shared/plainMarkdownText';
import { copyText } from '../bridge/meetingBridge';
import { CheckIcon, CloseIcon, CopyIcon, PinIcon, ThumbDownIcon, ThumbUpIcon } from '../components/MeetingIcons';
import { MeetingMarkdown } from '../lib/markdown';
import { useCompanionLinks } from './companionLinks';
import CompanionActionButtons from './CompanionActionButtons';
import type { CompanionFeedbackAction, CompanionItem, CompanionItemAction, CompanionItemActionResult, CompanionProposalInfo, FileCitation } from './types';

export const KIND_LABELS: Record<CompanionItem['kind'], string> = {
  insight: 'Insight',
  suggestion: 'Suggestion',
  answer: 'Answer',
  context_note: 'From your sources',
  proposal: 'Proposed action',
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

/** What became of a note's to-do or agent-task click, shown in place of the buttons. */
export function linkedActionText(proposal: CompanionProposalInfo): string {
  switch (proposal.state) {
    case 'started':
      return proposal.action === 'agent_task' ? 'Handed to an agent.' : 'Added to your To-Do list.';
    case 'failed':
      return 'The action could not be started. Retry it from the card below.';
    case 'handed_off':
      return 'Opened in an Assistant Session.';
    default:
      return 'An action for this note is waiting below.';
  }
}

interface CompanionItemCardProps {
  item: CompanionItem;
  watchTopic: string | null;
  onFeedback: (itemId: string, action: CompanionFeedbackAction) => Promise<boolean>;
  /** True when research is on and this note has not been researched yet. */
  canInvestigate: boolean;
  onInvestigate: (item: CompanionItem) => void;
  /** The reader's question this researched answer replies to. */
  replyQuote?: string | null;
  /** The action card already made from this note, when there is one; it replaces the buttons. */
  linkedAction?: CompanionItem | null;
  /** Which of Make to-do and Hand to agent are on in the Companion settings; none hides the buttons. */
  allowedActions?: readonly CompanionItemAction[];
  onAction?: (itemId: string, action: CompanionItemAction) => Promise<CompanionItemActionResult | null>;
  /** True when the reader has folded this note to its header and a one-line preview. The note stays in the stream; only dismissing removes it. */
  collapsed?: boolean;
  /** Folds or unfolds the note. Without it the card shows no chevron and is always open. */
  onToggleCollapsed?: (itemId: string) => void;
}

function CompanionItemCard({ item, watchTopic, onFeedback, canInvestigate, onInvestigate, replyQuote = null, linkedAction = null, allowedActions = [], onAction, collapsed = false, onToggleCollapsed }: CompanionItemCardProps) {
  const [copied, flashCopied] = useCopiedFlag();
  const [rating, setRating] = useState<'useful' | 'not_useful' | null>(null);
  const links = useCompanionLinks();
  const canShowInTranscript = links?.canShowInTranscript(item) === true;
  const isLinked = links?.hoveredItemId === item.id;

  const rate = (next: 'useful' | 'not_useful') => {
    setRating(next);
    void onFeedback(item.id, next);
  };

  const linkedProposal = linkedAction?.proposal ?? null;
  const canAct = onAction !== undefined && linkedProposal === null && item.kind !== 'proposal' && allowedActions.length > 0;

  const copy = () => {
    copyText(itemCopyText(item));
    flashCopied();
    void onFeedback(item.id, 'copied');
  };

  const isCollapsed = collapsed && onToggleCollapsed !== undefined;
  const showEvidenceRow = item.citations.length > 0 || item.researched === true;

  return (
    <article
      className={`companion-item companion-item--${item.kind}${item.pinned ? ' is-pinned' : ''}${isLinked ? ' is-linked' : ''}${isCollapsed ? ' is-collapsed' : ''}`}
      aria-label={`${KIND_LABELS[item.kind]} at ${formatItemTime(item)}`}
      onMouseEnter={links ? () => links.hover(item.id) : undefined}
      onMouseLeave={links ? () => links.hover(null) : undefined}
    >
      <header className="companion-item-header">
        {onToggleCollapsed && (
          <button
            type="button"
            className="meeting-transcript-icon-button companion-item-collapse"
            aria-label={isCollapsed ? 'Expand' : 'Collapse'}
            title={isCollapsed ? 'Expand this note' : 'Collapse this note'}
            aria-expanded={!isCollapsed}
            onClick={() => onToggleCollapsed(item.id)}
          >
            <ExecutionDisclosureChevron expanded={!isCollapsed} color="currentColor" />
          </button>
        )}
        <span className="companion-item-kind">{KIND_LABELS[item.kind]}</span>
        {watchTopic !== null && <span className="meeting-status-message">Watch: {watchTopic}</span>}
        <span className="meeting-transcription-state" title="Where this happened in the meeting">{formatItemTime(item)}</span>
        {canShowInTranscript && links && (
          <button type="button" className="companion-link-chip" title="Scroll the transcript to where this came up" onClick={() => links.showInTranscript(item)}>
            Show in transcript
          </button>
        )}
        <button type="button" className="meeting-transcript-icon-button companion-item-dismiss" aria-label="Dismiss" title="Dismiss" onClick={() => void onFeedback(item.id, 'dismissed')}>
          <CloseIcon />
        </button>
      </header>
      {isCollapsed ? (
        <p className="companion-item-preview">{plainMarkdownText(item.text)}</p>
      ) : (
        <>
          {replyQuote !== null && replyQuote !== '' && <p className="companion-item-quote">In reply to: “{replyQuote}”</p>}
          <div className="companion-item-body">
            <MeetingMarkdown content={item.text} />
          </div>
          {item.rationale !== undefined && item.rationale !== '' && (
            <details className="companion-rationale">
              <summary>Why this?</summary>
              <p>{item.rationale}</p>
            </details>
          )}
          {linkedProposal !== null && <p className="companion-item-note">{linkedActionText(linkedProposal)}</p>}
          {item.truncated && <p className="companion-item-note">This answer was cut short to fit.</p>}
          {item.no_source && <p className="companion-item-note">Not from your files. Based on the conversation alone.</p>}
          {showEvidenceRow && (
            <div className="companion-item-evidence">
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
              {item.researched === true && <span className="companion-badge" title={item.evidence_count ? `Based on ${item.evidence_count} pieces of evidence` : 'Based on research'}>Researched</span>}
            </div>
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
            <CompanionActionButtons
              allowedActions={canAct ? allowedActions : []}
              onAction={(action) => (onAction ? onAction(item.id, action) : Promise.resolve(null))}
              onInvestigate={canInvestigate ? () => onInvestigate(item) : undefined}
            />
          </footer>
        </>
      )}
    </article>
  );
}

export default memo(CompanionItemCard);
