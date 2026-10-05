import { useEffect, useRef, useState, type ClipboardEvent, type CSSProperties } from 'react';
import type { TodoItemDetail } from '../contracts';
import RichTextComposer from '../../../shared/RichTextComposer';
import {
  pickTodoReferenceFiles,
  registerTodoReferenceFilesPickedHandler,
} from '../services/bridge';
import { sanitizeRichText } from './richTextSanitize';
import { isTodoDueDateOverdue } from './todoDates';
import TodoDeleteConfirmation from './TodoDeleteConfirmation';
import TodoWorkerStatusCard from './TodoWorkerStatusCard';
import type { TodoWorkerLiveState } from './useTodoWorkerProgress';
import { plainMarkdownText } from '@shared/plainMarkdownText';

const todoEditPencilURL = new URL('../../../shared/assets/native-symbols/assistant-pencil.png', import.meta.url).href;
const todoEditPencilStyle: CSSProperties = {
  width: 14,
  height: 14,
  display: 'block',
  backgroundColor: 'currentColor',
  WebkitMaskImage: `url("${todoEditPencilURL}")`,
  WebkitMaskPosition: 'center',
  WebkitMaskRepeat: 'no-repeat',
  WebkitMaskSize: 'contain',
  maskImage: `url("${todoEditPencilURL}")`,
  maskPosition: 'center',
  maskRepeat: 'no-repeat',
  maskSize: 'contain',
};

interface TodoDetailPaneProps {
  item: TodoItemDetail | null;
  onSaveDetails: (title: string, description: string) => Promise<void>;
  onSaveNotes: (notes: string) => Promise<void>;
  onSaveDueDate: (dueAt: string | null) => Promise<void>;
  onSaveCompletedDate: (completedAt: string | null) => Promise<void>;
  onAddReference: (path: string) => Promise<void | TodoItemDetail>;
  onRemoveReference: (referenceId: string) => Promise<void | TodoItemDetail>;
  onAccept: () => Promise<void>;
  onDismiss: () => Promise<void>;
  onComplete: () => Promise<void>;
  onReopen: () => Promise<void>;
  onCancel: () => Promise<void>;
  onDelete: () => Promise<void>;
  onLaunchWorker: () => Promise<void>;
  workerProgress: Record<string, TodoWorkerLiveState>;
  onRefreshAfterConflict: () => void;
  conflictMessage: string | null;
}

function referenceBasename(path: string): string {
  const trimmedPath = path.replace(/\/+$/, '');
  const segments = trimmedPath.split('/');
  return segments[segments.length - 1] || path;
}

function formatTodoStatus(status: string): string {
  return status === 'canceled' ? 'Canceled' : status.replace(/_/g, ' ');
}

function formatTodoDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

export default function TodoDetailPane({
  item, onSaveDetails, onSaveNotes, onSaveDueDate, onSaveCompletedDate, onAddReference, onRemoveReference,
  onAccept, onDismiss, onComplete, onReopen, onCancel, onDelete, onLaunchWorker, workerProgress, onRefreshAfterConflict, conflictMessage,
}: TodoDetailPaneProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(item?.title ?? '');
  const [draftDescriptionHtml, setDraftDescriptionHtml] = useState(() => sanitizeRichText(item?.description ?? ''));
  const [draftNotesHtml, setDraftNotesHtml] = useState(() => sanitizeRichText(item?.notes ?? ''));
  const descriptionEditorRef = useRef<HTMLDivElement>(null);
  const notesEditorRef = useRef<HTMLDivElement>(null);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  const [savingDetails, setSavingDetails] = useState(false);
  const [savingNotes, setSavingNotes] = useState(false);
  const [savingDueDate, setSavingDueDate] = useState(false);
  const [savingCompletedDate, setSavingCompletedDate] = useState(false);
  const [isEditingDueDate, setIsEditingDueDate] = useState(false);
  const [isEditingCompletedDate, setIsEditingCompletedDate] = useState(false);
  const [savingReference, setSavingReference] = useState(false);
  const [launchingWorker, setLaunchingWorker] = useState(false);
  const [confirmingDeletion, setConfirmingDeletion] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setIsEditing(false);
    setDraftTitle(item?.title ?? '');
    setDraftDescriptionHtml(sanitizeRichText(item?.description ?? ''));
    setDraftNotesHtml(sanitizeRichText(item?.notes ?? ''));
    if (notesEditorRef.current) notesEditorRef.current.innerHTML = sanitizeRichText(item?.notes ?? '');
    setReferenceError(null);
    setConfirmingDeletion(false);
    setDeleting(false);
    setIsEditingDueDate(false);
    setIsEditingCompletedDate(false);
  }, [item?.id, item?.title, item?.description, item?.notes]);

  useEffect(() => {
    if (isEditing && descriptionEditorRef.current) {
      descriptionEditorRef.current.innerHTML = draftDescriptionHtml;
    }
    // The editor is only mounted in edit mode; it must be seeded when that mode opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing]);

  function forcePlainTextPaste(event: ClipboardEvent<HTMLDivElement>): void {
    event.preventDefault();
    document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
  }

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

  const isDirty = draftNotesHtml !== sanitizeRichText(item.notes);
  const isDetailDirty = draftTitle.trim() !== item.title || draftDescriptionHtml !== sanitizeRichText(item.description);
  const isTerminal = ['completed', 'dismissed', 'canceled'].includes(item.status);

  async function saveDetails(): Promise<void> {
    if (!draftTitle.trim() || !isDetailDirty || savingDetails) return;
    setSavingDetails(true);
    try {
      await onSaveDetails(draftTitle.trim(), sanitizeRichText(draftDescriptionHtml));
      setIsEditing(false);
    } finally {
      setSavingDetails(false);
    }
  }

  async function saveNotes(): Promise<void> {
    if (!isDirty || savingNotes) return;
    setSavingNotes(true);
    try {
      await onSaveNotes(sanitizeRichText(draftNotesHtml));
    } finally {
      setSavingNotes(false);
    }
  }

  function cancelEdit(): void {
    if (!item) return;
    setDraftTitle(item.title);
    const description = sanitizeRichText(item.description);
    setDraftDescriptionHtml(description);
    if (descriptionEditorRef.current) descriptionEditorRef.current.innerHTML = description;
    setIsEditing(false);
  }

  return (
    <div className="todo-detail-pane">
      <header className="todo-detail-header">
        <div className="todo-detail-header-main">
          {isEditing ? (
            <input
              className="todo-detail-title-input"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              maxLength={240}
              aria-label="To-Do title"
            />
          ) : (
            <h2 className="todo-detail-title">{plainMarkdownText(item.title)}</h2>
          )}
          <span className="todo-detail-status">{formatTodoStatus(item.status)}</span>
        </div>
        <button
          type="button"
          className="todo-detail-edit-toggle"
          onClick={() => (isEditing ? cancelEdit() : setIsEditing(true))}
          aria-label={isEditing ? 'Cancel edit' : 'Edit To-Do'}
          title={isEditing ? 'Cancel edit' : 'Edit To-Do'}
        >
          {isEditing ? 'Cancel edit' : <span aria-hidden="true" style={todoEditPencilStyle} />}
        </button>
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
      {isEditing && (
        <section className="todo-detail-edit-form" aria-label="Edit To-Do">
          <label>
            Description
            <RichTextComposer
              editorRef={descriptionEditorRef}
              className="todo-detail-rich-text-composer todo-detail-description-composer"
              disabled={savingDetails}
              placeholder="Describe this To-Do"
              submitDisabled={!draftTitle.trim() || !isDetailDirty || savingDetails}
              onDraftChange={() => {}}
              onHtmlChange={setDraftDescriptionHtml}
              onPaste={forcePlainTextPaste}
              onSubmit={() => void saveDetails()}
              editorAriaLabel="To-Do description"
              showActions={false}
            />
          </label>
          <div className="todo-detail-edit-actions">
            <button
              type="button"
              disabled={!draftTitle.trim() || !isDetailDirty || savingDetails}
              onClick={() => void saveDetails()}
            >
              Save changes
            </button>
            <button type="button" disabled={savingDetails} onClick={cancelEdit}>
              Discard
            </button>
          </div>
        </section>
      )}
      {conflictMessage && (
        <div className="todo-detail-conflict" role="alert">
          <p>{conflictMessage}</p>
          <button type="button" onClick={onRefreshAfterConflict}>Refresh latest</button>
        </div>
      )}
      {!isEditing && (item.description ? (
        <div className="todo-detail-description" dangerouslySetInnerHTML={{ __html: sanitizeRichText(item.description) }} />
      ) : (
        <p className="todo-detail-description">No description.</p>
      ))}
      <section className="todo-detail-notes">
        <h3>Notes</h3>
        <RichTextComposer
          editorRef={notesEditorRef}
          className="todo-detail-rich-text-composer"
          disabled={savingNotes}
          placeholder="Add notes"
          submitDisabled={!isDirty || savingNotes}
          onDraftChange={() => {}}
          onHtmlChange={setDraftNotesHtml}
          onPaste={forcePlainTextPaste}
          onSubmit={() => void saveNotes()}
          editorAriaLabel="To-Do notes"
          showActions={false}
        />
        <div className="todo-detail-notes-actions">
          <button
            type="button"
            disabled={!isDirty || savingNotes}
            onClick={() => void saveNotes()}
          >
            Save notes
          </button>
          <button
            type="button"
            disabled={!isDirty}
            onClick={() => {
              const notes = sanitizeRichText(item.notes);
              setDraftNotesHtml(notes);
              if (notesEditorRef.current) notesEditorRef.current.innerHTML = notes;
            }}
          >
            Discard
          </button>
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
