import { CollapsedHistoryRail } from '../../../shared/HistorySidebarControls';

interface CompanionRailProps {
  onExpand: () => void;
  /** What is waiting in the hidden pane ("3 new", "1 to decide"); nothing shows when null. */
  badge?: string | null;
  /** The Companion is open in its own window: the rail raises that window instead of expanding a pane, and carries no badge. */
  detached?: boolean;
}

const DETACHED_LABEL = 'The Companion is open in its own window. Bring it to front.';

/** The collapsed Companion: the History rail's expand control, mirrored for the right edge. A badge reports what arrived while the pane was hidden. */
export default function CompanionRail({ onExpand, badge = null, detached = false }: CompanionRailProps) {
  const shownBadge = detached ? null : badge;
  return (
    <aside className="companion-rail" aria-label="Companion">
      <CollapsedHistoryRail
        ariaLabel={detached ? DETACHED_LABEL : shownBadge ? `Show the Companion, ${shownBadge}` : 'Show the Companion'}
        title={detached ? DETACHED_LABEL : 'Show the Companion'}
        onExpand={onExpand}
        classNames={{ symbol: 'companion-mirrored-symbol' }}
      />
      {shownBadge && <span className="companion-badge-count" aria-hidden="true">{shownBadge.split(' ')[0]}</span>}
    </aside>
  );
}
