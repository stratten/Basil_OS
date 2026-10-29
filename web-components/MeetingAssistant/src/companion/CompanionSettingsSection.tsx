import type { ReactNode } from 'react';
import CollapsibleRegion from '../../../shared/CollapsibleRegion';
import ExecutionDisclosureChevron from '../../../shared/ExecutionDisclosureChevron';

interface CompanionSettingsSectionProps {
  open: boolean;
  onToggle: () => void;
  /** What is configured, shown while the section is closed. */
  summary: string;
  children: ReactNode;
}

/** The Companion's controls (sources, watches, research, proposals, focus, reasoning model) in one section above the stream, so the settings that shape the output sit at the top and the interaction sits at the bottom. Closed, it is one line that says what is configured; the content stays mounted so typed text survives. */
export default function CompanionSettingsSection({ open, onToggle, summary, children }: CompanionSettingsSectionProps) {
  return (
    <section className="companion-settings" aria-label="Companion settings">
      <button type="button" className="companion-settings-toggle" aria-expanded={open} onClick={onToggle}>
        <ExecutionDisclosureChevron expanded={open} />
        <span className="companion-settings-title">Companion settings</span>
        {!open && <span className="companion-settings-summary">{summary}</span>}
      </button>
      <CollapsibleRegion expanded={open}>
        <div className="companion-settings-body">{children}</div>
      </CollapsibleRegion>
    </section>
  );
}
