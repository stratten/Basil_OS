import { useChecklist, useChecklistCounts } from '../../store/checklistStore';
import { openChecklistWindow } from '../../store/checklistViewStore';
import { checklistCounterLabel, checklistPillTone } from './checklistPresentation';

interface Props {
  rootTaskId: string;
}

/**
 * The checklist counter at the top of the run rail, above the first turn. It has a fixed height, so a chain with dozens of turns never pushes it out of view, and it appears only once the chain has items. Pressing it opens the checklist window; the short list lives in the Run overview.
 */
export default function ChecklistRailPill({ rootTaskId }: Props) {
  useChecklist(rootTaskId);
  const counts = useChecklistCounts(rootTaskId);
  if (counts.total === 0) return null;
  const label = checklistCounterLabel(counts);

  return (
    <div className="agent-run-rail-checklist">
      <button
        type="button"
        className={`agent-run-rail-checklist-pill is-${checklistPillTone(counts)}`}
        aria-label={`${label}. Open the checklist`}
        data-tooltip={label}
        data-tooltip-placement="left"
        onClick={() => openChecklistWindow(rootTaskId)}
      >
        <span className="agent-run-rail-checklist-pill__part">{counts.done}</span>
        <span className="agent-run-rail-checklist-pill__part">/{counts.total}</span>
      </button>
    </div>
  );
}
