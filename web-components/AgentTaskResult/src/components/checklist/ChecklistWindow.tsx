import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { ModalCloseButton } from '@shared/dialogs/ModalCloseButton';
import type { ChecklistItem } from '../../services/checklistApi';
import { checklistActions, useChecklist, useChecklistCounts } from '../../store/checklistStore';
import { closeChecklistWindow, useChecklistWindowItemId, useChecklistWindowRoot } from '../../store/checklistViewStore';
import ChecklistAddForm from './ChecklistAddForm';
import ChecklistItemDetail from './ChecklistItemDetail';
import ChecklistNotesEditor from './ChecklistNotesEditor';
import ChecklistStatusGlyph from './ChecklistStatusGlyph';
import { checklistItemAriaLabel, isInferredDone, isOpenStatus, prioritizeChecklistItems } from './checklistPresentation';

interface Props {
  rootTaskId: string;
  onNavigateRun?: (runId: string) => void;
  /** True while an approval or checkpoint is on screen. The window stays mounted (so nothing typed is lost) but steps aside. */
  yielding?: boolean;
}

type Tab = 'items' | 'notes';
type Filter = 'open' | 'all' | 'archived';

function filterItems(items: readonly ChecklistItem[], filter: Filter): ChecklistItem[] {
  if (filter === 'archived') {
    return items.filter(item => item.archived_at).sort((left, right) => right.updated_at.localeCompare(left.updated_at));
  }
  const visible = prioritizeChecklistItems(items);
  return filter === 'open' ? visible.filter(item => isOpenStatus(item.status)) : visible;
}

/**
 * Everything about a chain's checklist in one modal: every item (done and archived too), each item's step log and references, the working notes, and the actions to add, edit, archive and close. It opens only when the reader asks, and steps aside for approvals and checkpoints.
 */
export default function ChecklistWindow({ rootTaskId, onNavigateRun, yielding = false }: Props) {
  const windowRoot = useChecklistWindowRoot();
  const targetItemId = useChecklistWindowItemId();
  const isOpen = windowRoot === rootTaskId;
  const { entry, refresh } = useChecklist(rootTaskId, isOpen);
  const counts = useChecklistCounts(rootTaskId);
  const [tab, setTab] = useState<Tab>('items');
  const [filter, setFilter] = useState<Filter>('open');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const actions = useMemo(() => checklistActions(rootTaskId), [rootTaskId]);
  const snapshot = entry.snapshot;
  const items = snapshot?.items ?? [];
  const openCount = items.filter(item => !item.archived_at && isOpenStatus(item.status)).length;
  const archivedCount = items.filter(item => item.archived_at).length;
  const visible = useMemo(() => filterItems(items, filter), [items, filter]);

  useEffect(() => {
    if (!isOpen) return undefined;
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cardRef.current?.focus();
    return () => {
      returnFocus.current?.focus();
      setMessage(null);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !targetItemId) return;
    setTab('items');
    setExpandedId(targetItemId);
    const target = items.find(item => item.id === targetItemId);
    if (target) setFilter(target.archived_at ? 'archived' : isOpenStatus(target.status) ? 'open' : 'all');
    // Only the request to open on an item matters here, not later edits to the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, targetItemId]);

  if (!isOpen) return null;

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      closeChecklistWindow();
    }
  }

  async function toggleClosed() {
    setMessage(null);
    try {
      await actions.closeList(!snapshot?.closed_at);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'The checklist could not be updated.');
    }
  }

  const loading = entry.state === 'loading' && !snapshot;
  const failed = entry.state === 'error' && !snapshot;
  const emptyText = filter === 'open' && items.length > 0
    ? 'Nothing is open. Switch to All to see finished items.'
    : filter === 'archived'
      ? 'No archived items.'
      : 'No items yet. Add what still needs to happen.';

  return (
    <div className="checklist-window-region" hidden={yielding} {...(yielding ? { inert: '' } : {})}>
      <div className="overlay-backdrop checklist-window-backdrop" onClick={closeChecklistWindow}>
        <div
          ref={cardRef}
          className="overlay-card checklist-window"
          role="dialog"
          aria-modal="true"
          aria-labelledby="checklist-window-title"
          tabIndex={-1}
          onClick={event => event.stopPropagation()}
          onKeyDown={handleKeyDown}
        >
          <header className="checklist-window__header">
            <ModalCloseButton onClose={closeChecklistWindow} closeOnEscape={false} />
            <div className="checklist-window__heading">
              <h2 id="checklist-window-title" className="overlay-title checklist-window__title">Checklist</h2>
              <span className="checklist-window__count">{counts.done} of {counts.total} done{snapshot?.closed_at ? ', tracking stopped' : ''}</span>
            </div>
          </header>

          <div className="checklist-tabs" role="tablist" aria-label="Checklist sections">
            <button type="button" role="tab" id="checklist-tab-items" aria-selected={tab === 'items'} aria-controls="checklist-panel" className={`checklist-tab${tab === 'items' ? ' is-selected' : ''}`} onClick={() => setTab('items')}>Items</button>
            <button type="button" role="tab" id="checklist-tab-notes" aria-selected={tab === 'notes'} aria-controls="checklist-panel" className={`checklist-tab${tab === 'notes' ? ' is-selected' : ''}`} onClick={() => setTab('notes')}>Notes</button>
          </div>

          {message && <p className="checklist-window__message" role="alert">{message}</p>}

          <div id="checklist-panel" className="checklist-window__panel" role="tabpanel" aria-labelledby={tab === 'items' ? 'checklist-tab-items' : 'checklist-tab-notes'}>
            {loading && <p className="checklist-window__quiet" role="status">Loading the checklist...</p>}
            {failed && (
              <div className="checklist-window__failure" role="alert">
                <p>The checklist could not be loaded. {entry.error}</p>
                <button type="button" className="checklist-button" onClick={() => void refresh()}>Try again</button>
              </div>
            )}
            {snapshot && tab === 'items' && (
              <>
                <ChecklistAddForm actions={actions} />
                <div className="checklist-filters" role="group" aria-label="Which items to show">
                  {([['open', `Open ${openCount}`], ['all', `All ${items.length - archivedCount}`], ['archived', `Archived ${archivedCount}`]] as const).map(([value, label]) => (
                    <button key={value} type="button" className={`checklist-filter${filter === value ? ' is-selected' : ''}`} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>
                  ))}
                </div>
                {visible.length === 0 ? (
                  <p className="checklist-window__quiet">{emptyText}</p>
                ) : (
                  <ul className="checklist-window__items" aria-label="Checklist items">
                    {visible.map(item => {
                      const expanded = expandedId === item.id;
                      return (
                        <li key={item.id} className={`checklist-window__item${expanded ? ' is-expanded' : ''}`}>
                          <button
                            type="button"
                            className="checklist-row"
                            aria-expanded={expanded}
                            aria-label={checklistItemAriaLabel(item)}
                            onClick={() => setExpandedId(expanded ? null : item.id)}
                          >
                            <ChecklistStatusGlyph status={item.status} />
                            <span className="checklist-row__text">
                              <span className="checklist-row__title">{item.title}</span>
                              {(item.status === 'waiting_user' || item.status === 'waiting_external') && item.waiting_on && (
                                <span className="checklist-row__sub">{item.waiting_on}</span>
                              )}
                            </span>
                            {isInferredDone(item) && <span className="checklist-row__tag" title="Basil marked this done from what it could see. Open it to confirm or reopen it.">Inferred</span>}
                            {item.required && <span className="checklist-row__tag">Required</span>}
                            {item.origin === 'carried' && <span className="checklist-row__tag checklist-row__tag--quiet">Carried</span>}
                          </button>
                          {expanded && (
                            <ChecklistItemDetail
                              rootTaskId={rootTaskId}
                              item={item}
                              actions={actions}
                              onNavigateRun={onNavigateRun ? runId => { closeChecklistWindow(); onNavigateRun(runId); } : undefined}
                              onReport={setMessage}
                            />
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                {snapshot.exists && (
                  <div className="checklist-window__footer">
                    <p className="checklist-window__footer-text">
                      {snapshot.closed_at
                        ? 'Tracking is stopped, so Basil is not using this checklist.'
                        : 'Basil keeps this checklist up to date while it works.'}
                    </p>
                    <button type="button" className="checklist-button" onClick={() => void toggleClosed()}>
                      {snapshot.closed_at ? 'Resume tracking' : 'Stop tracking'}
                    </button>
                  </div>
                )}
              </>
            )}
            {snapshot && tab === 'notes' && (
              <ChecklistNotesEditor notes={snapshot.notes} maxChars={snapshot.notes_max_chars} actions={actions} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
