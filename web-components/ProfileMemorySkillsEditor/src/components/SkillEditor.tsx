import { useEffect, useState } from 'react';
import { deleteSkill, getSkill, ProfileEditorApiError, updateSkill } from '../services/api';
import { notifySaved } from '../services/bridge';

interface Props {
  apiBaseUrl: string;
  slug: string;
}

export function SkillEditor({ apiBaseUrl, slug }: Props) {
  const [title, setTitle] = useState('');
  const [whenToUse, setWhenToUse] = useState('');
  const [triggers, setTriggers] = useState('');
  const [body, setBody] = useState('');
  const [version, setVersion] = useState(1);
  const [observationCount, setObservationCount] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [pendingAction, setPendingAction] = useState<null | 'save' | 'delete'>(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

  useEffect(() => {
    let canceled = false;
    setIsLoading(true);
    setHasLoaded(false);
    setError(null);
    setIsConfirmingDelete(false);
    getSkill(apiBaseUrl, slug)
      .then((skill) => {
        if (canceled) return;
        setHasLoaded(true);
        setTitle(skill.title);
        setWhenToUse(skill.when_to_use);
        setTriggers(skill.triggers.join(', '));
        setBody(skill.body);
        setVersion(skill.version);
        setObservationCount(skill.observation_count);
      })
      .catch((err) => {
        if (!canceled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!canceled) setIsLoading(false);
      });
    return () => {
      canceled = true;
    };
  }, [apiBaseUrl, slug]);

  async function save() {
    if (isLoading || pendingAction !== null) return;
    setError(null);
    setPendingAction('save');
    try {
      await updateSkill(apiBaseUrl, slug, {
        title,
        when_to_use: whenToUse,
        triggers: splitTriggers(triggers),
        body,
      });
      notifySaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPendingAction(null);
    }
  }

  function requestDelete() {
    if (!hasLoaded || isLoading || pendingAction !== null) return;
    setIsConfirmingDelete(true);
  }

  function cancelDelete() {
    setIsConfirmingDelete(false);
  }

  async function confirmDelete() {
    if (isLoading || pendingAction !== null) return;
    setIsConfirmingDelete(false);
    setError(null);
    setPendingAction('delete');
    try {
      const result = await deleteSkill(apiBaseUrl, slug);
      if (result.deleted) notifySaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPendingAction(null);
    }
  }

  const isDisabled = !hasLoaded || isLoading || pendingAction !== null;
  const operationLabel = isLoading ? 'Loading…' : pendingAction === 'save' ? 'Saving…' : pendingAction === 'delete' ? 'Deleting…' : null;

  return (
    <section className="editor-panel">
      {error && <div className="editor-error">{error}</div>}
      {operationLabel && <div className="editor-operation-status" aria-live="polite">{operationLabel}</div>}
      <div className="editor-context">
        v{version} · observed {observationCount} time{observationCount === 1 ? '' : 's'}
      </div>
      <input className="editor-input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Title" disabled={isDisabled} />
      <textarea className="editor-textarea editor-textarea--short" value={whenToUse} onChange={(event) => setWhenToUse(event.target.value)} placeholder="When to use" disabled={isDisabled} />
      <input className="editor-input" value={triggers} onChange={(event) => setTriggers(event.target.value)} placeholder="Triggers, comma separated" disabled={isDisabled} />
      <textarea className="editor-textarea editor-textarea--mono" value={body} onChange={(event) => setBody(event.target.value)} disabled={isDisabled} />
      <div className="editor-footer">
        {isConfirmingDelete ? (
          <>
            <span className="editor-context">Delete this saved skill?</span>
            <button className="editor-secondary-button" onClick={cancelDelete} disabled={isDisabled}>Cancel</button>
            <button className="editor-danger-button" onClick={confirmDelete} disabled={isDisabled}>Confirm Delete</button>
          </>
        ) : (
          <button className="editor-danger-button" onClick={requestDelete} disabled={isDisabled}>{pendingAction === 'delete' ? 'Deleting…' : 'Delete'}</button>
        )}
        <button className="editor-primary-button" onClick={save} disabled={isDisabled}>{pendingAction === 'save' ? 'Saving…' : 'Save'}</button>
      </div>
    </section>
  );
}

function splitTriggers(value: string) {
  return value.split(',').map((trigger) => trigger.trim()).filter(Boolean);
}

function errorMessage(error: unknown) {
  return error instanceof ProfileEditorApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : String(error);
}
