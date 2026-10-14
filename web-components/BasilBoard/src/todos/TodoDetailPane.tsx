import { useEffect, useRef, useState, type ClipboardEvent, type FocusEvent, type KeyboardEvent } from 'react';
import type { TodoItemDetail, TodoStatus } from '../contracts';
import RichTextComposer from '../../../shared/RichTextComposer';
import TokenizedSelect from '../../../shared/TokenizedSelect';
import {
  pickTodoReferenceFiles,
  registerTodoReferenceFilesPickedHandler,
} from '../services/bridge';
import { sanitizeRichText } from './richTextSanitize';
import { isTodoDueDateOverdue } from './todoDates';
import TodoDeleteConfirmation from './TodoDeleteConfirmation';
import TodoWorkerStatusCard from './TodoWorkerStatusCard';
import type { TodoWorkerLiveState } from './useTodoWorkerProgress';
import useAutosaveField, { type AutosaveStatus } from './useAutosaveField';

interface TodoDetailPaneProps {
  item: TodoItemDetail | null;
  onSaveTitle: (title: string) => Promise<boolean>;
  onSaveDescription: (description: string) => Promise<boolean>;
  onSaveNotes: (notes: string) => Promise<boolean>;
  onSaveDueDate: (dueAt: string | null) => Promise<boolean>;
  onSaveCompletedDate: (completedAt: string | null) => Promise<boolean>;
  onSetStatus: (status: TodoStatus) => Promise<unknown>;
  onAddReference: (path: string) => Promise<void | TodoItemDetail>;
  onRemoveReference: (referenceId: string) => Promise<void | TodoItemDetail>;
  onAccept: () => Promise<unknown>;
  onDismiss: () => Promise<unknown>;
  onComplete: () => Promise<unknown>;
  onReopen: () => Promise<unknown>;
  onCancel: () => Promise<unknown>;
  onDelete: () => Promise<unknown>;
  onLaunchWorker: () => Promise<unknown>;
  workerProgress: Record<string, TodoWorkerLiveState>;
  onRefreshAfterConflict: () => void;
  conflictMessage: string | null;
}

const TODO_STATUS_OPTIONS: Array<{ value: TodoStatus; label: string }> = [
  { value: 'candidate', label: 'Candidate' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'ready_for_review', label: 'Ready for review' },
  { value: 'completed', label: 'Completed' },
  { value: 'dismissed', label: 'Dismissed' },
  { value: 'canceled', label: 'Canceled' },
];

function referenceBasename(path: string): string {
  const trimmedPath = path.replace(/\/+$/, '');
  const segments = trimmedPath.split('/');
  return segments[segments.length - 1] || path;
}

function formatTodoDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

/** Stored rich text with the browser's empty-editor placeholders (`<br>`, empty blocks) collapsed to nothing. */
function normalizeRichField(value: string): string {
  const sanitized = sanitizeRichText(value);
  const container = document.createElement('div');
  container.innerHTML = sanitized;
  const hasText = (container.textContent ?? '').trim().length > 0;
  const hasStructure = container.querySelector('ul, ol, pre') !== null;
  return hasText || hasStructure ? sanitized : '';
}

function normalizeTitle(value: string): string {
  return value.trim();
}

function aggregateSaveStatus(statuses: AutosaveStatus[]): AutosaveStatus {
  if (statuses.includes('error')) return 'error';
  if (statuses.includes('saving')) return 'saving';
  if (statuses.includes('saved')) return 'saved';
  return 'idle';
}

const SAVE_STATUS_LABELS: Record<AutosaveStatus, string> = {
  idle: '',
  saving: 'Saving…',
  saved: 'Saved',
  error: 'Not saved. Click away or press Enter to retry.',
};

function forcePlainTextPaste(event: ClipboardEvent<HTMLDivElement>): void {
  event.preventDefault();
  document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
}

function setEditorHtml(editor: HTMLDivElement | null, value: string): void {
  if (editor) editor.innerHTML = sanitizeRichText(value);
}

export default function TodoDetailPane({
  item, onSaveTitle, onSaveDescription, onSaveNotes, onSaveDueDate, onSaveCompletedDate, onSetStatus,
  onAddReference, onRemoveReference,
  onAccept, onDismiss, onComplete, onReopen, onCancel, onDelete, onLaunchWorker, workerProgress, onRefreshAfterConflict, conflictMessage,
}: TodoDetailPaneProps) {
  const descriptionEditorRef = useRef<HTMLDivElement>(null);
  const notesEditorRef = useRef<HTMLDivElement>(null);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  const [pendingStatus, setPendingStatus] = useState<TodoStatus | null>(null);
  const [savingDueDate, setSavingDueDate] = useState(false);
  const [savingCompletedDate, setSavingCompletedDate] = useState(false);
  const [isEditingDueDate, setIsEditingDueDate] = useState(false);
  const [isEditingCompletedDate, setIsEditingCompletedDate] = useState(false);
  const [savingReference, setSavingReference] = useState(false);
  const [launchingWorker, setLaunchingWorker] = useState(false);
  const [confirmingDeletion, setConfirmingDeletion] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const itemId = item?.id ?? '';
  const title = useAutosaveField({
    itemId,
    serverValue: item?.title ?? '',
    normalize: normalizeTitle,
    isValid: (value) => value.length > 0,
    save: onSaveTitle,
  });
  const description = useAutosaveField({
    itemId,
    serverValue: item?.description ?? '',
    normalize: normalizeRichField,
    save: onSaveDescription,
    onProgrammaticChange: (value) => setEditorHtml(descriptionEditorRef.current, value),
  });
  const notes = useAutosaveField({
    itemId,
    serverValue: item?.notes ?? '',
    normalize: normalizeRichField,
    save: onSaveNotes,
    onProgrammaticChange: (value) => setEditorHtml(notesEditorRef.current, value),
  });
  const saveStatus = aggregateSaveStatus([
    title.status, description.status, notes.status,
  ]);

  useEffect(() => {
    // The rich editors are uncontrolled; seed them whenever a different To-Do is shown.
    setEditorHtml(descriptionEditorRef.current, item?.description ?? '');
    setEditorHtml(notesEditorRef.current, item?.notes ?? '');
    setPendingStatus(null);
    setIsEditingDueDate(false);
    setIsEditingCompletedDate(false);
    setReferenceError(null);
    setConfirmingDeletion(false);
    setDeleting(false);
    // Only the identity of the To-Do re-seeds the editors; later server updates flow through useAutosaveField.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id]);

  async function addReferencePaths(rawPaths: string[]): Promise<void> {
    const paths = [...new Set(rawPaths.map((path) => path.trim()).filter(Boolean))];
    const invalidPath = paths.find((path) => !path.startsWith('/'));
    if (invalidPath) {
      setReferenceError('Attachments must use absolute local paths.');
      return;
    }
    setSavingReference(true);
    setReferenceError(null);
    try {
      for (const path of paths) {
        await onAddReference(path);
      }
    } catch (error) {
      setReferenceError(error instanceof Error ? error.message : 'Could not attach files or folders.');
    } finally {
      setSavingReference(false);
    }
  }

  useEffect(() => registerTodoReferenceFilesPickedHandler((paths) => {
    void addReferencePaths(paths);
  }), [item?.id, onAddReference]);

  if (!item) {
    return <div className="todo-detail-pane todo-detail-pane--empty">Select a To-Do to see its details.</div>;
  }

  const isTerminal = ['completed', 'dismissed', 'canceled'].includes(item.status);

  function handleTitleKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      event.currentTarget.blur();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      title.revert();
      event.currentTarget.blur();
    }
  }

  function richFieldBlurHandler(field: typeof description) {
    return (event: FocusEvent<HTMLDivElement>) => {
      if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
      field.onBlur();
    };
  }

  function richFieldKeyDown(field: typeof description) {
    return (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      field.revert();
      (event.target as HTMLElement).blur();
    };
  }

  async function changeStatus(nextStatus: TodoStatus): Promise<void> {
    setPendingStatus(nextStatus);
    try {
      await onSetStatus(nextStatus);
    } finally {
      setPendingStatus(null);
    }
  }

  return (
    <div className="todo-detail-pane">
      <header className="todo-detail-header">
        <div className="todo-detail-header-main">
          <input
            className="todo-detail-title-input"
            value={title.draft}
            onChange={(event) => title.setDraft(event.target.value)}
            onFocus={title.onFocus}
            onBlur={title.onBlur}
            onKeyDown={handleTitleKeyDown}
            maxLength={240}
            aria-label="To-Do title"
          />
          <div className="todo-detail-status-row">
            <TokenizedSelect
              className="todo-detail-status"
              ariaLabel="Status"
              value={pendingStatus ?? item.status}
              options={TODO_STATUS_OPTIONS}
              disabled={pendingStatus !== null}
              onValueChange={(nextStatus) => void changeStatus(nextStatus)}
            />
            <span className="todo-detail-save-status" role="status" aria-live="polite" data-state={saveStatus}>
              {SAVE_STATUS_LABELS[saveStatus]}
            </span>
          </div>
        </div>
      </header>
      <section className="todo-detail-dates">
        <div className="todo-detail-date-group">
          <h3>Created date</h3>
          <span>{formatTodoDate(item.created_at)}</span>
        </div>
        <div className="todo-detail-date-group">
          <h3>Due date</h3>
          {isEditingDueDate ? (
            <div className="todo-detail-due-controls">
              <input
                type="date"
                value={item.due_at ? item.due_at.slice(0, 10) : ''}
                aria-label="Due date"
                autoFocus
                disabled={savingDueDate}
                onChange={async (event) => {
                  const value = event.target.value;
                  setSavingDueDate(true);
                  try {
                    await onSaveDueDate(value ? new Date(`${value}T00:00:00Z`).toISOString() : null);
                  } finally {
                    setSavingDueDate(false);
                    setIsEditingDueDate(false);
                  }
                }}
              />
              {item.due_at && (
                <button
                  type="button"
                  className="todo-detail-due-clear"
                  disabled={savingDueDate}
                  onClick={async () => {
                    setSavingDueDate(true);
                    try {
                      await onSaveDueDate(null);
                    } finally {
                      setSavingDueDate(false);
                      setIsEditingDueDate(false);
                    }
                  }}
                >
                  Clear
                </button>
              )}
              <button type="button" className="todo-detail-date-edit-cancel" disabled={savingDueDate} onClick={() => setIsEditingDueDate(false)}>
                Cancel
              </button>
            </div>
          ) : (
            <div className="todo-detail-date-display">
              <button type="button" className="todo-detail-date-display-value" onClick={() => setIsEditingDueDate(true)}>
                {item.due_at ? formatTodoDate(item.due_at) : 'Add due date'}
              </button>
              {item.due_at && isTodoDueDateOverdue(item.due_at) && !isTerminal && (
                <span className="todo-detail-due-overdue">Overdue</span>
              )}
            </div>
          )}
        </div>
        {item.status === 'completed' && (
          <div className="todo-detail-date-group">
            <h3>Completed date</h3>
            {isEditingCompletedDate ? (
              <div className="todo-detail-completed-controls">
                <input
                  type="date"
                  value={item.completed_at ? item.completed_at.slice(0, 10) : ''}
                  aria-label="Completed date"
                  autoFocus
                  disabled={savingCompletedDate}
                  onChange={async (event) => {
                    const value = event.target.value;
                    setSavingCompletedDate(true);
                    try {
                      await onSaveCompletedDate(value ? new Date(`${value}T00:00:00Z`).toISOString() : null);
                    } finally {
                      setSavingCompletedDate(false);
                      setIsEditingCompletedDate(false);
                    }
                  }}
                />
                {item.completed_at && (
                  <button
                    type="button"
                    className="todo-detail-due-clear"
                    disabled={savingCompletedDate}
                    onClick={async () => {
                      setSavingCompletedDate(true);
                      try {
                        await onSaveCompletedDate(null);
                      } finally {
                        setSavingCompletedDate(false);
                        setIsEditingCompletedDate(false);
                      }
                    }}
                  >
                    Clear
                  </button>
                )}
                <button type="button" className="todo-detail-date-edit-cancel" disabled={savingCompletedDate} onClick={() => setIsEditingCompletedDate(false)}>
                  Cancel
                </button>
              </div>
            ) : (
              <div className="todo-detail-date-display">
                <button type="button" className="todo-detail-date-display-value" onClick={() => setIsEditingCompletedDate(true)}>
                  {item.completed_at ? formatTodoDate(item.completed_at) : 'Add completed date'}
                </button>
              </div>
            )}
          </div>
        )}
      </section>
      {conflictMessage && (
        <div className="todo-detail-conflict" role="alert">
          <p>{conflictMessage}</p>
          <button type="button" onClick={onRefreshAfterConflict}>Refresh latest</button>
        </div>
      )}
      <section className="todo-detail-description-section">
        <h3>Description</h3>
        <div
          className="todo-detail-field"
          onFocus={description.onFocus}
          onBlur={richFieldBlurHandler(description)}
        >
          <RichTextComposer
            editorRef={descriptionEditorRef}
            className="todo-detail-rich-text-composer todo-detail-description-composer"
            disabled={false}
            placeholder="Describe this To-Do"
            submitDisabled={false}
            onDraftChange={() => {}}
            onHtmlChange={description.setDraft}
            onPaste={forcePlainTextPaste}
            onKeyDown={richFieldKeyDown(description)}
            onSubmit={() => void description.commit()}
            editorAriaLabel="To-Do description"
            showActions={false}
          />
        </div>
      </section>
      <section className="todo-detail-notes">
        <h3>Notes</h3>
        <div
          className="todo-detail-field"
          onFocus={notes.onFocus}
          onBlur={richFieldBlurHandler(notes)}
        >
          <RichTextComposer
            editorRef={notesEditorRef}
            className="todo-detail-rich-text-composer"
            disabled={false}
            placeholder="Add notes"
            submitDisabled={false}
            onDraftChange={() => {}}
            onHtmlChange={notes.setDraft}
            onPaste={forcePlainTextPaste}
            onKeyDown={richFieldKeyDown(notes)}
            onSubmit={() => void notes.commit()}
            editorAriaLabel="To-Do notes"
            showActions={false}
          />
        </div>
      </section>
      <section className="todo-detail-references">
        <div className="todo-detail-section-heading">
          <h3>Attachments</h3>
          <button
            type="button"
            className="todo-detail-attach-button"
            disabled={savingReference}
            onClick={pickTodoReferenceFiles}
            title="Attach files or folders"
            aria-label="Attach files or folders"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
            </svg>
          </button>
        </div>
        {item.references.length === 0 ? <p>No attachments yet.</p> : (
          <ul>
            {item.references.map((reference) => (
              <li key={reference.id}>
                <span title={reference.path}>{referenceBasename(reference.path)}</span>
                <button
                  type="button"
                  disabled={savingReference}
                  onClick={async () => {
                    setSavingReference(true);
                    setReferenceError(null);
                    try {
                      await onRemoveReference(reference.id);
                    } catch (error) {
                      setReferenceError(error instanceof Error ? error.message : 'Could not remove the attachment.');
                    } finally {
                      setSavingReference(false);
                    }
                  }}
                  aria-label={`Remove ${reference.path}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        {referenceError && <p className="todo-detail-reference-error" role="alert">{referenceError}</p>}
      </section>
      <section className="todo-detail-sources">
        <h3>Provenance</h3>
        {item.sources.length === 0 ? (
          <p>Created manually.</p>
        ) : (
          <ul>
            {item.sources.map((source) => (
              <li key={source.id}>{source.source_kind}: {source.source_excerpt || source.source_id}</li>
            ))}
          </ul>
        )}
      </section>
      <section className="todo-detail-work-history">
        <h3>Work history</h3>
        {item.worker_attempts.length === 0 ? (
          <p>No Paprika tasks yet.</p>
        ) : (
          <div className="todo-worker-status-card-list">
            {item.worker_attempts.map((attempt) => (
              <TodoWorkerStatusCard
                key={attempt.agent_task_id}
                attempt={attempt}
                liveState={workerProgress[attempt.agent_task_id]}
              />
            ))}
          </div>
        )}
      </section>
      <section className="todo-detail-actions">
        {item.status === 'candidate' && (
          <>
            <button type="button" onClick={() => onAccept()}>Accept</button>
            <button type="button" onClick={() => onDismiss()}>Dismiss</button>
          </>
        )}
        {(item.status === 'open' || item.status === 'in_progress') && (
          <button
            type="button"
            className="todo-detail-action-primary"
            disabled={launchingWorker}
            onClick={async () => {
              setLaunchingWorker(true);
              try {
                await onLaunchWorker();
              } finally {
                setLaunchingWorker(false);
              }
            }}
          >
            {launchingWorker ? 'Starting worker…' : 'Start agent on this'}
          </button>
        )}
        {(item.status === 'open' || item.status === 'in_progress' || item.status === 'ready_for_review') && (
          <button type="button" className="todo-detail-action-primary" onClick={() => onComplete()}>Mark complete</button>
        )}
        {isTerminal && (
          <button type="button" onClick={() => onReopen()}>Reopen</button>
        )}
        {(item.status === 'open' || item.status === 'in_progress') && (
          <button type="button" onClick={() => onCancel()}>Cancel</button>
        )}
        {!confirmingDeletion && (
          <button type="button" className="todo-detail-action-delete" onClick={() => setConfirmingDeletion(true)}>
            Delete To-Do
          </button>
        )}
      </section>
      {confirmingDeletion && (
        <TodoDeleteConfirmation
          className="todo-detail-delete-confirmation"
          isDeleting={deleting}
          onConfirm={() => {
            void (async () => {
              setDeleting(true);
              try {
                await onDelete();
              } finally {
                setDeleting(false);
              }
            })();
          }}
          onCancel={() => setConfirmingDeletion(false)}
        />
      )}
    </div>
  );
}
