import { useState, type ReactNode } from 'react';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';

export function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="assistant-output-history-collapsible">
      <button type="button" className="assistant-output-history-collapsible__header" aria-expanded={open} onClick={() => setOpen((prev) => !prev)}>
        <span>
          <span className="assistant-output-history-collapsible__chevron" aria-hidden="true">
            <ExecutionDisclosureChevron expanded={open} color="var(--secondary, #4c7bf0)" />
          </span>
          {title}
        </span>
      </button>
      {open && <div className="assistant-output-history-collapsible__body">{children}</div>}
    </div>
  );
}
