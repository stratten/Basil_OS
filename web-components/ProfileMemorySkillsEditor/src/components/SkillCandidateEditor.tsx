import { useEffect, useState } from 'react';
import { approveSkillCandidate, declineSkillCandidate, getAgentTaskSummary, getSkillCandidate, ProfileEditorApiError } from '../services/api';
import { notifyDeclined, notifySaved, openSourceTask } from '../services/bridge';
import type { AgentTaskSummary } from '../types';

interface Props {
  apiBaseUrl: string;
  candidateId: string;
}

export function SkillCandidateEditor({ apiBaseUrl, candidateId }: Props) {
  const [title, setTitle] = useState('');
  const [whenToUse, setWhenToUse] = useState('');
  const [triggers, setTriggers] = useState('');
  const [procedure, setProcedure] = useState('');
  const [sourceTaskIds, setSourceTaskIds] = useState<string[]>([]);
  const [sourceTasks, setSourceTasks] = useState<Record<string, AgentTaskSummary | null>>({});
  const [enhancesSkillSlug, setEnhancesSkillSlug] = useState<string | null>(null);
  const [observationCount, setObservationCount] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [pendingAction, setPendingAction] = useState<null | 'approve' | 'decline'>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setHasLoaded(false);
    setError(null);
    getSkillCandidate(apiBaseUrl, candidateId)
      .then((candidate) => {
        if (!candidate) throw new Error('Skill candidate not found');
        if (cancelled) return;
        setHasLoaded(true);
        setTitle(candidate.title);
        setWhenToUse(candidate.when_to_use);
        setTriggers(candidate.triggers.join(', '));
        setProcedure(candidate.procedure_markdown);
        setSourceTaskIds(candidate.source_task_ids);
        setEnhancesSkillSlug(candidate.enhances_skill_slug ?? null);
        setObservationCount(candidate.observation_count);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, candidateId]);

  useEffect(() => {
    if (sourceTaskIds.length === 0) return;
    let cancelled = false;
    Promise.allSettled(sourceTaskIds.map((id) => getAgentTaskSummary(apiBaseUrl, id))).then((results) => {
      if (cancelled) return;
      const next: Record<string, AgentTaskSummary | null> = {};
      results.forEach((result, index) => {
        next[sourceTaskIds[index]] = result.status === 'fulfilled' ? result.value : null;
      });
      setSourceTasks(next);
    });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, sourceTaskIds]);

  async function approve() {
    if (!hasLoaded || isLoading || pendingAction !== null) return;
    setError(null);
    setPendingAction('approve');
    try {
      await approveSkillCandidate(apiBaseUrl, candidateId, {
        title,
        when_to_use: whenToUse,
        triggers: splitTriggers(triggers),
        procedure_markdown: procedure,
      });
      notifySaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPendingAction(null);
    }
  }

  async function decline() {
    if (!hasLoaded || isLoading || pendingAction !== null) return;
    setError(null);
    setPendingAction('decline');
    try {
      await declineSkillCandidate(apiBaseUrl, candidateId);
      notifyDeclined();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPendingAction(null);
    }
  }

  const isDisabled = !hasLoaded || isLoading || pendingAction !== null;
  const operationLabel = isLoading ? 'Loading…' : pendingAction === 'approve' ? 'Approving…' : pendingAction === 'decline' ? 'Declining…' : null;

  return (
    <section className="editor-panel">
      {error && <div className="editor-error">{error}</div>}
      {operationLabel && <div className="editor-operation-status" aria-live="polite">{operationLabel}</div>}
      <div className="editor-context">
        Observed {observationCount} time{observationCount === 1 ? '' : 's'}
      </div>
      {enhancesSkillSlug && (
        <div className="editor-context editor-context--enhance">
          Approving updates the saved skill: <strong>{enhancesSkillSlug}</strong>
        </div>
      )}
      <input className="editor-input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Title" disabled={isDisabled} />
      <textarea className="editor-textarea editor-textarea--short" value={whenToUse} onChange={(event) => setWhenToUse(event.target.value)} placeholder="When to use" disabled={isDisabled} />
      <input className="editor-input" value={triggers} onChange={(event) => setTriggers(event.target.value)} placeholder="Triggers, comma separated" disabled={isDisabled} />
      <textarea className="editor-textarea editor-textarea--mono" value={procedure} onChange={(event) => setProcedure(event.target.value)} disabled={isDisabled} />
      <div className="editor-source-tasks">
        <span className="editor-source-tasks-label">Source tasks</span>
        {sourceTaskIds.length === 0 ? (
          <span className="editor-context">None recorded</span>
        ) : (
          <ul className="editor-source-task-list">
            {sourceTaskIds.map((id) => {
              const summary = sourceTasks[id];
              if (summary) {
                const label = (summary.title || summary.original_prompt || summary.transcribed_prompt || id).trim();
                return (
                  <li key={id}>
                    <button
                      type="button"
                      className="editor-source-task-link"
                      title={label}
                      onClick={() => openSourceTask(id)}
                      disabled={isDisabled}
                    >
                      {truncate(label)}
                    </button>
                  </li>
                );
              }
              if (summary === null) {
                return (
                  <li key={id}>
                    <span className="editor-source-task-unavailable">Task unavailable ({id})</span>
                  </li>
                );
              }
              return (
                <li key={id}>
                  <span className="editor-source-task-loading">Loading task… ({id})</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <div className="editor-footer">
        <button className="editor-danger-button" onClick={decline} disabled={isDisabled}>{pendingAction === 'decline' ? 'Declining…' : 'Decline'}</button>
        <button className="editor-primary-button" onClick={approve} disabled={isDisabled}>
          {pendingAction === 'approve' ? 'Approving…' : enhancesSkillSlug ? 'Approve & Update Skill' : 'Approve'}
        </button>
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

function truncate(text: string, max = 90) {
  const collapsed = text.replace(/\s+/g, ' ').trim();
  return collapsed.length > max ? `${collapsed.slice(0, max - 1)}…` : collapsed;
}
