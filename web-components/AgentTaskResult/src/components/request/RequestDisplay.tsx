import { useEffect, useRef, useState } from 'react';
import MarkdownRenderer from '../MarkdownRenderer';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import AgentTaskOriginChip from './AgentTaskOriginChip';

interface Props {
  originalPrompt: string;
  displayPromptMarkdown?: string;
  originType?: string;
  originId?: string;
}

export function hasClippedRequestContent(scrollHeight: number, clientHeight: number): boolean {
  return scrollHeight - clientHeight > 2;
}

export default function RequestDisplay({
  originalPrompt,
  displayPromptMarkdown,
  originType,
  originId,
}: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const content = displayPromptMarkdown?.trim() || originalPrompt;

  useEffect(() => {
    setIsExpanded(false);
  }, [content]);

  useEffect(() => {
    const preview = previewRef.current;
    if (!preview || isExpanded) return;

    const measureOverflow = () => {
      setHasOverflow(hasClippedRequestContent(preview.scrollHeight, preview.clientHeight));
    };
    measureOverflow();

    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measureOverflow);
    observer.observe(preview);
    return () => observer.disconnect();
  }, [content, isExpanded]);

  if (!content) return null;

  return (
    <section className="request-display">
      <div className="request-display-label-row">
        <div className="request-display-label">Request</div>
        <AgentTaskOriginChip originType={originType} originId={originId} />
      </div>
      <div
        ref={previewRef}
        className={`request-display-content${hasOverflow ? ' has-overflow' : ''}${isExpanded ? ' is-expanded' : ''}`}
      >
        <MarkdownRenderer content={content} variant="request" />
      </div>
      {hasOverflow && (
        <button
          type="button"
          className="request-display-toggle"
          aria-expanded={isExpanded}
          onClick={() => setIsExpanded(current => !current)}
        >
          <span>{isExpanded ? 'Hide full request' : 'Show full request'}</span>
          <ExecutionDisclosureChevron expanded={isExpanded} />
        </button>
      )}
    </section>
  );
}
