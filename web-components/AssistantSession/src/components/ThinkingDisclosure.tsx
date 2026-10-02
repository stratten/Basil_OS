import { useEffect, useState } from 'react';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import PresenceRegion from '@shared/PresenceRegion';
import { normalizedThinkingMarkdown } from '../lib/thinkingMarkdown';
import { MarkdownView } from './MarkdownView';

export function ThinkingDisclosure({
  content,
  startsExpanded = false,
  isActive = false,
}: {
  content: string;
  startsExpanded?: boolean;
  isActive?: boolean;
}) {
  const [expanded, setExpanded] = useState(startsExpanded);
  const [ellipsisPhase, setEllipsisPhase] = useState(0);

  useEffect(() => {
    setExpanded(startsExpanded);
  }, [startsExpanded]);

  useEffect(() => {
    if (!isActive) {
      setEllipsisPhase(0);
      return;
    }
    const timer = window.setInterval(() => {
      setEllipsisPhase((phase) => (phase + 1) % 4);
    }, 450);
    return () => window.clearInterval(timer);
  }, [isActive]);

  if (!content) return null;
  const normalized = normalizedThinkingMarkdown(content);
  const headerLabel = isActive ? `Thinking${'.'.repeat(ellipsisPhase)}` : 'Thinking';

  return (
    <div className="assistant-session-thinking">
      <button type="button" className="assistant-session-thinking__toggle" aria-expanded={expanded} onClick={() => setExpanded((prev) => !prev)}>
        <span className="assistant-session-thinking__chevron" aria-hidden="true">
          <ExecutionDisclosureChevron expanded={expanded} color="var(--secondary, #4c7bf0)" />
        </span>
        <span className="assistant-session-thinking__label">{headerLabel}</span>
      </button>
      <PresenceRegion visible={expanded} className="basil-presence" settleWithoutTransition>
        <div className="assistant-session-thinking__body">
          <MarkdownView content={normalized} />
        </div>
      </PresenceRegion>
    </div>
  );
}
