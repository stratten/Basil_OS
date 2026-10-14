import { CollapsedHistoryRail } from '../../../shared/HistorySidebarControls';

/** The collapsed Companion: the History rail's expand control, mirrored for the right edge. */
export default function CompanionRail({ onExpand }: { onExpand: () => void }) {
  return (
    <aside className="companion-rail" aria-label="Companion">
      <CollapsedHistoryRail ariaLabel="Show the Companion" title="Show the Companion" onExpand={onExpand} classNames={{ symbol: 'companion-mirrored-symbol' }} />
    </aside>
  );
}
