import { useEffect, useState } from 'react';
import type { ActionDecision, ActionEditFields, ProposedAction, SessionSnapshot } from '../types';
import { KIND_LABELS, KINDS_WITH_BODY } from '../app/actionMeta';
import { DiffView } from './DiffView';

interface ActionDetailProps {
  action: ProposedAction;
  snapshot: SessionSnapshot;
  locked: boolean;
  onDecide: (decision: ActionDecision, edited?: ActionEditFields) => void;
}

export function ActionDetail({ action, snapshot, locked, onDecide }: ActionDetailProps) {
  const hasBody = KINDS_WITH_BODY.includes(action.kind);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState('');
  const [whenToUse, setWhenToUse] = useState('');
  const [triggersText, setTriggersText] = useState('');
  const [procedure, setProcedure] = useState('');
  const [expected, setExpected] = useState('');

  useEffect(() => {
    const edited = action.user_edited ?? {};
    setEditing(false);
    setTitle(edited.title ?? action.merged_title ?? '');
    setWhenToUse(edited.when_to_use ?? action.merged_when_to_use ?? '');
    setTriggersText((edited.triggers ?? action.merged_triggers).join('\n'));
    setProcedure(edited.procedure_markdown ?? action.merged_procedure_markdown ?? '');
    setExpected(edited.expected_result ?? action.merged_expected_result ?? '');
  }, [action.id]);

  const buildEdited = (): ActionEditFields => ({
    title,
    when_to_use: whenToUse,
    triggers: triggersText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    procedure_markdown: procedure,
    expected_result: expected,
  });

  const accept = () => onDecide('accepted', hasBody ? buildEdited() : undefined);
  const reject = () => onDecide('rejected');

  const beforeText = computeBeforeText(action, snapshot);
  const afterText = hasBody ? (editing ? procedure : action.merged_procedure_markdown ?? '') : '';

  return (
    <div className="action-detail-pane">
      <span className={`risk-badge kind-${action.kind}`}>{KIND_LABELS[action.kind]}</span>

      <p className="detail-rationale">{action.rationale}</p>

      {hasBody ? (
        <div className="agent-task-card">
          <DiffView
            beforeLabel={action.kind === 'keep_new' ? 'Candidate' : 'Current'}
            afterLabel="Proposed"
            before={beforeText}
            after={afterText}
          />
          {editing ? (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label className="detail-section-label">Title</label>
              <input className="edit-field" value={title} onChange={(e) => setTitle(e.target.value)} />
              <label className="detail-section-label">When to use</label>
              <textarea className="edit-field" rows={2} value={whenToUse} onChange={(e) => setWhenToUse(e.target.value)} />
              <label className="detail-section-label">Triggers (one per line)</label>
              <textarea className="edit-field" rows={3} value={triggersText} onChange={(e) => setTriggersText(e.target.value)} />
              <label className="detail-section-label">Procedure</label>
              <textarea className="edit-field" rows={10} value={procedure} onChange={(e) => setProcedure(e.target.value)} />
              <label className="detail-section-label">Expected result</label>
              <textarea className="edit-field" rows={2} value={expected} onChange={(e) => setExpected(e.target.value)} />
            </div>
          ) : (
            <div style={{ marginTop: 12 }}>
              <div className="detail-field">
                <span className="detail-section-label">Title</span>
                <span className="value">{title || '—'}</span>
              </div>
              <div className="detail-field">
                <span className="detail-section-label">When to use</span>
                <span className="value">{whenToUse || '—'}</span>
              </div>
              <div className="detail-field">
                <span className="detail-section-label">Triggers</span>
                <span className="value">
                  {triggersText
                    .split('\n')
                    .filter(Boolean)
                    .map((trigger) => (
                      <span className="trigger-chip" key={trigger}>
                        {trigger}
                      </span>
                    ))}
                </span>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="agent-task-card">
          <div className="result-action-message info">
            {action.kind === 'duplicate_of_saved_skill'
              ? 'Accepting will decline this candidate as already covered by the saved skill below.'
              : 'Accepting will delete the saved skill below (a backup is written first).'}
          </div>
          <div className="diff-column before">
            <div className="diff-column-label">
              Saved skill{action.target_skill_slug ? `: ${action.target_skill_slug}` : ''}
            </div>
            <div className="diff-body">{beforeText || '—'}</div>
          </div>
        </div>
      )}

      <div className="detail-actions">
        {hasBody && (
          <button className="action-btn" onClick={() => setEditing((value) => !value)} disabled={locked}>
            {editing ? 'Done editing' : 'Edit merged skill'}
          </button>
        )}
        <button className="action-btn success" onClick={accept} disabled={locked}>
          {action.decision === 'accepted' ? 'Accepted ✓ (update)' : 'Accept'}
        </button>
        <button className="action-btn danger" onClick={reject} disabled={locked}>
          {action.decision === 'rejected' ? 'Rejected ✓ (update)' : 'Reject'}
        </button>
      </div>
    </div>
  );
}

function computeBeforeText(action: ProposedAction, snapshot: SessionSnapshot): string {
  if (action.kind === 'merge_candidates') {
    const parts = action.source_candidate_ids
      .map((id) => snapshot.pending_candidates.find((candidate) => candidate.id === id))
      .filter((candidate): candidate is NonNullable<typeof candidate> => Boolean(candidate))
      .map((candidate) => `## ${candidate.title}\n${candidate.procedure_markdown}`);
    return parts.join('\n\n———\n\n');
  }
  if (action.kind === 'keep_new') {
    const candidate = snapshot.pending_candidates.find(
      (item) => item.id === action.source_candidate_ids[0],
    );
    return candidate ? candidate.procedure_markdown : '';
  }
  // enhance / duplicate / delete → the saved skill body.
  const saved = snapshot.saved_skills.find((skill) => skill.slug === action.target_skill_slug);
  return saved ? saved.body : '';
}
