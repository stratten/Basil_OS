import { useEffect, useState } from 'react';
import TokenizedSelect from '../../../../shared/TokenizedSelect';
import * as checklistApi from '../../services/checklistApi';
import type { ChecklistItem, ChecklistItemLog, ChecklistStatus } from '../../services/checklistApi';
import type { ChecklistActions } from '../../store/checklistStore';
import {
  CHECKLIST_STATUS_LABEL,
  CHECKLIST_TITLE_MAX_CHARS,
  CHECKLIST_STATUS_OPTIONS,
  checklistActorLabel,
  checklistEventSummary,
  checklistRefLabel,
  checklistRefSystem,
  safeChecklistRefUrl,
} from './checklistPresentation';
import { useChecklistItemDraft, type ChecklistDraftField } from './useChecklistItemDraft';

interface Props {
  rootTaskId: string;
  item: ChecklistItem;
  actions: ChecklistActions;
  onNavigateRun?: (runId: string) => void;
  onReport: (message: string | null) => void;
}

const STATUS_OPTIONS = CHECKLIST_STATUS_OPTIONS.map(value => ({ value, label: CHECKLIST_STATUS_LABEL[value] }));

type LogState = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; log: ChecklistItemLog };

function conflictMessage(error: unknown): string {
  if (checklistApi.isChecklistConflict(error)) return 'This changed while you were editing it. The latest version is shown, and anything you typed is kept so you can save it again.';
  return error instanceof Error ? error.message : 'That change could not be saved.';
}

/** The expanded half of a checklist row: edit fields, references, the item's step log, and the actions that apply to it. */
export default function ChecklistItemDetail({ rootTaskId, item, actions, onNavigateRun, onReport }: Props) {
  const { draft, setField, dirtyChanges, restoreBlankTitle } = useChecklistItemDraft(item);
  const [logState, setLogState] = useState<LogState>({ kind: 'loading' });
  const [todoNotice, setTodoNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const waiting = item.status === 'waiting_user' || item.status === 'waiting_external';

  useEffect(() => {
    let current = true;
    setLogState(previous => (previous.kind === 'ready' ? previous : { kind: 'loading' }));
    checklistApi.getChecklistItemLog(rootTaskId, item.id)
      .then(log => { if (current) setLogState({ kind: 'ready', log }); })
      .catch(error => { if (current) setLogState({ kind: 'error', message: error instanceof Error ? error.message : 'The step log could not be loaded.' }); });
    return () => { current = false; };
  }, [rootTaskId, item.id, item.revision]);

  async function run(work: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    onReport(null);
    try {
      await work();
      return true;
    } catch (error) {
      onReport(conflictMessage(error));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function commitField(field: ChecklistDraftField) {
    const changes = dirtyChanges();
    if (field === 'title') restoreBlankTitle();
    if (Object.keys(changes).length === 0) return;
    await run(() => actions.updateItem(item.id, { ...changes, expected_revision: item.revision }));
  }

  const textField = (field: ChecklistDraftField, label: string, multiline: boolean, maxLength?: number) => {
    const id = `checklist-${item.id}-${field}`;
    return (
      <div className="checklist-field">
        <label className="checklist-field__label" htmlFor={id}>{label}</label>
        {multiline ? (
          <textarea
            id={id}
            className="checklist-field__input checklist-field__input--multiline"
            value={draft[field]}
            rows={3}
            maxLength={maxLength}
            onChange={event => setField(field, event.target.value)}
            onBlur={() => void commitField(field)}
          />
        ) : (
          <input
            id={id}
            className="checklist-field__input"
            value={draft[field]}
            maxLength={maxLength}
            onChange={event => setField(field, event.target.value)}
            onBlur={() => void commitField(field)}
          />
        )}
      </div>
    );
  };

  return (
    <div className="checklist-detail">
      <div className="checklist-detail__controls">
        <div className="checklist-field checklist-field--compact">
          <span className="checklist-field__label" id={`checklist-${item.id}-status-label`}>Status</span>
          <TokenizedSelect<ChecklistStatus>
            value={item.status}
            options={STATUS_OPTIONS}
            ariaLabel={`Status of ${item.title}`}
            disabled={busy}
            onValueChange={status => void run(() => actions.updateItem(item.id, { status, expected_revision: item.revision }))}
          />
        </div>
        <label className="checklist-detail__required">
          <input
            type="checkbox"
            checked={item.required}
            disabled={busy}
            onChange={event => void run(() => actions.updateItem(item.id, { required: event.target.checked, expected_revision: item.revision }))}
          />
          <span>Required before the run is finished</span>
        </label>
      </div>
      {item.refs.length > 0 && (
        <div className="checklist-detail__section">
          <h4 className="checklist-detail__heading">References</h4>
          <ul className="checklist-refs">
            {item.refs.map(ref => {
              const url = safeChecklistRefUrl(ref);
              return (
                <li key={ref.id} className="checklist-refs__item">
                  <span className="checklist-refs__system">{checklistRefSystem(ref)}</span>
                  {url ? (
                    <a className="checklist-refs__label" href={url} target="_blank" rel="noreferrer">{checklistRefLabel(ref)}</a>
                  ) : (
                    <span className="checklist-refs__label">{checklistRefLabel(ref)}</span>
                  )}
                  {ref.last_known_status && <span className="checklist-refs__status">{ref.last_known_status}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="checklist-detail__actions">
        <button type="button" className="checklist-button" aria-expanded={showMore} onClick={() => setShowMore(!showMore)}>
          {showMore ? 'Hide details and history' : 'Edit details and history'}
        </button>
        {item.updated_by_task_id && onNavigateRun && (
          <button type="button" className="checklist-button" onClick={() => onNavigateRun(item.updated_by_task_id!)}>
            Go to the run that last changed this
          </button>
        )}
        {item.status === 'waiting_user' && (
          <button
            type="button"
            className="checklist-button"
            disabled={busy || todoNotice !== null}
            onClick={() => void run(async () => {
              await actions.offerAsTodo(item.id);
              setTodoNotice('Offered as a To-Do. Accept it in your To-Dos to keep it.');
            })}
          >
            Offer as a To-Do
          </button>
        )}
        <button
          type="button"
          className="checklist-button"
          disabled={busy}
          onClick={() => void run(() => actions.archiveItem(item.id, !item.archived_at))}
        >
          {item.archived_at ? 'Restore' : 'Archive'}
        </button>
      </div>
      {todoNotice && <p className="checklist-detail__quiet" role="status">{todoNotice}</p>}
      {showMore && (
        <div className="checklist-detail__more">
          {textField('title', 'Step', true, CHECKLIST_TITLE_MAX_CHARS)}
          {waiting && textField('waiting_on', item.status === 'waiting_user' ? 'What you need to do' : 'Who or what it is waiting on', false)}
          {textField('detail', 'Details', true)}
          {textField('note', 'Note', true)}

          <div className="checklist-detail__section">
            <h4 className="checklist-detail__heading">Step log</h4>
            {logState.kind === 'loading' && <p className="checklist-detail__quiet">Loading the step log...</p>}
            {logState.kind === 'error' && <p className="checklist-detail__quiet" role="alert">{logState.message}</p>}
            {logState.kind === 'ready' && (
              <>
                {logState.log.events.length === 0 && <p className="checklist-detail__quiet">Nothing has been logged for this item yet.</p>}
                <ol className="checklist-log">
                  {logState.log.events.map(event => (
                    <li key={event.id} className="checklist-log__entry">
                      <span className="checklist-log__actor">{checklistActorLabel(event.actor)}</span>
                      <span className="checklist-log__text">{checklistEventSummary(event.kind, event.text)}</span>
                    </li>
                  ))}
                </ol>
                {logState.log.captured.length > 0 && (
                  <>
                    <h4 className="checklist-detail__heading">Actions Basil took for this item</h4>
                    <ul className="checklist-log">
                      {logState.log.captured.map((action, index) => (
                        <li key={`${action.service}.${action.method}.${action.created_at}.${index}`} className="checklist-log__entry">
                          <span className="checklist-log__actor">{action.material_write ? 'Changed something' : 'Read'}</span>
                          <span className="checklist-log__text">{action.service}.{action.method}: {action.execution_state}, {action.verification_status}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
