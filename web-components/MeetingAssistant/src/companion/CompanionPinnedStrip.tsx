import CollapsibleRegion from '../../../shared/CollapsibleRegion';
import ExecutionDisclosureChevron from '../../../shared/ExecutionDisclosureChevron';
import { plainMarkdownText } from '../../../shared/plainMarkdownText';
import { PinIcon } from '../components/MeetingIcons';
import { useCopiedFlag } from '../../../shared/useCopyFeedback';
import { copyText } from '../bridge/meetingBridge';
import { CheckIcon, CopyIcon } from '../components/MeetingIcons';
import { formatItemTime, itemCopyText, KIND_LABELS } from './CompanionItemCard';
import type { CompanionItem } from './types';

interface CompanionPinnedStripProps {
  items: CompanionItem[];
  open: boolean;
  onToggle: () => void;
  /** Scrolls the stream to the item's full card, which stays in the stream. */
  onJump: (itemId: string) => void;
}

/** One compact row per pinned item above the stream. The full card never moves out of the stream, so chronology is kept; a row only takes the reader to it. */
/** Everything pinned as one block of text, each item with its time, kind and sources, in the order they arrived. */
export function pinnedItemsCopyText(items: CompanionItem[]): string {
  return items.map((item) => `${formatItemTime(item)} ${KIND_LABELS[item.kind]}\n${itemCopyText(item)}`).join('\n\n');
}

export default function CompanionPinnedStrip({ items, open, onToggle, onJump }: CompanionPinnedStripProps) {
  const [copied, flashCopied] = useCopiedFlag();
  if (items.length === 0) return null;
  const copyAll = () => {
    copyText(pinnedItemsCopyText(items));
    flashCopied();
  };
  return (
    <section className="companion-pinned-strip" aria-label="Pinned">
      <div className="companion-pinned-header">
        <button type="button" className="companion-pinned-toggle" aria-expanded={open} onClick={onToggle}>
          <ExecutionDisclosureChevron expanded={open} />
          <PinIcon filled />
          <span>Pinned ({items.length})</span>
        </button>
        <button type="button" className="meeting-transcript-icon-button companion-pinned-copy" aria-label={copied ? 'Copied pinned items' : 'Copy pinned items'} title={copied ? 'Copied' : 'Copy pinned items'} onClick={copyAll}>
          {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
      </div>
      <CollapsibleRegion expanded={open}>
        <ul className="companion-pinned-list">
          {items.map((item) => (
            <li key={item.id}>
              <button type="button" className="companion-pinned-row" onClick={() => onJump(item.id)}>
                <span className="companion-pinned-kind">{KIND_LABELS[item.kind]}</span>
                <span className="companion-pinned-text">{plainMarkdownText(item.text)}</span>
                <span className="meeting-transcription-state">{formatItemTime(item)}</span>
              </button>
            </li>
          ))}
        </ul>
      </CollapsibleRegion>
    </section>
  );
}
