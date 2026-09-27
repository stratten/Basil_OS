import { useState } from 'react';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';

export function ContextSection({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="assistant-session-result__section">
      <button type="button" className="assistant-session-result__section-toggle" aria-expanded={expanded} onClick={() => setExpanded((prev) => !prev)}>
        <span aria-hidden="true">
          <ExecutionDisclosureChevron expanded={expanded} color="var(--secondary, #4c7bf0)" />
        </span>
        <span>Context</span>
        <span className="assistant-session-result__char-count">({text.length} chars)</span>
      </button>
      {expanded && <div className="assistant-session-result__context-body">{text}</div>}
    </div>
  );
}
