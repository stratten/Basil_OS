import { useMemo } from 'react';
import { useChecklist, useChecklistCounts } from '../../store/checklistStore';
import { openChecklistWindow } from '../../store/checklistViewStore';
import ChecklistStatusGlyph from './ChecklistStatusGlyph';
import { checklistItemAriaLabel, OVERVIEW_ROW_LIMIT, prioritizeChecklistItems } from './checklistPresentation';

interface Props {
  rootTaskId: string;
}

/**
 * The checklist's short form, at the top of the Run overview. It lists the few items that matter most (what needs the reader first), one line each with its status mark, and "Show all" opens the full checklist window. It renders nothing until the chain has items, and a row opens the window on that item.
 */
export default function ChecklistOverviewSection({ rootTaskId }: Props) {
  const { entry } = useChecklist(rootTaskId);
  const counts = useChecklistCounts(rootTaskId);
  const items = useMemo(() => prioritizeChecklistItems(entry.snapshot?.items ?? []), [entry.snapshot]);

  if (items.length === 0 && counts.total === 0) return null;
  const rows = items.slice(0, OVERVIEW_ROW_LIMIT);
  const needsInput = counts.waitingUser;

  return (
    <section className="checklist-overview" aria-label="Checklist">
      <header className="checklist-overview__header">
        <h3 className="checklist-overview__title">Checklist</h3>
        <span className="checklist-overview__count">{counts.done} of {counts.total} done</span>
        {needsInput > 0 && <span className="checklist-overview__flag">{needsInput} need{needsInput === 1 ? 's' : ''} your input</span>}
        {counts.closed && <span className="checklist-overview__stopped">Tracking stopped</span>}
      </header>
      {entry.state === 'error' && <p className="checklist-overview__error" role="alert">The checklist could not be refreshed. {entry.error}</p>}
      <ul className="checklist-overview__rows" aria-label="Checklist items">
        {rows.map(item => (
          <li key={item.id}>
            <button
              type="button"
              className="checklist-overview__row"
              aria-label={checklistItemAriaLabel(item)}
              onClick={() => openChecklistWindow(rootTaskId, item.id)}
            >
              <ChecklistStatusGlyph status={item.status} />
              <span className="checklist-overview__text">
                <span className="checklist-overview__row-title">{item.title}</span>
                {(item.status === 'waiting_user' || item.status === 'waiting_external') && item.waiting_on && (
                  <span className="checklist-overview__row-sub">{item.waiting_on}</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <button type="button" className="checklist-overview__open" onClick={() => openChecklistWindow(rootTaskId)}>
        {items.length > rows.length ? `Show all ${items.length}` : 'Open checklist'}
      </button>
    </section>
  );
}
