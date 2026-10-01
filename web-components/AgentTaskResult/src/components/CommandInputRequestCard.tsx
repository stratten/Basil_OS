import { useState } from 'react';
import type { ExecutionApprovalRequest } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';

interface Props {
  agentTaskId: string;
  approval: ExecutionApprovalRequest;
  embedded?: boolean;
}

function formatExpiry(expiresAt?: number): string | null {
  if (typeof expiresAt !== 'number' || !Number.isFinite(expiresAt)) return null;
  return new Date(expiresAt * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export default function CommandInputRequestCard({ agentTaskId, approval, embedded = false }: Props) {
  const metadata = approval.command_input;
  const [value, setValue] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const secret = metadata?.secret ?? false;
  const prompt = metadata?.prompt || approval.reason;
  const expiry = formatExpiry(metadata?.expires_at);
  const inputId = `command-input-${approval.approval_id}`;

  const finish = (message: string) => {
    agentStore.removeApproval(agentTaskId, approval.approval_id);
    agentStore.updateProgressStep(agentTaskId, message, true, false);
  };

  const submit = async (action: 'answer' | 'cancel') => {
    if (!metadata) {
      setError('This input request is missing its details. Stop the task and try again.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.submitCommandInput({
        request_id: metadata.request_id,
        agent_task_id: metadata.agent_task_id,
        action,
        value: action === 'answer' ? value : undefined,
      });
      setValue('');
      finish(action === 'answer' ? 'Input sent, continuing...' : 'Command stopped, continuing...');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (/\((404|409)\)|not pending/i.test(message)) {
        setValue('');
        finish('The command is no longer waiting for input.');
        return;
      }
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={embedded ? 'approval-set-card' : 'overlay-backdrop'}>
      <form
        className="overlay-card"
        aria-label="Command input request"
        data-agent-desk-interactive-overlay="true"
        data-preferred-content-width={480}
        style={{ maxWidth: 'clamp(360px, 60vw, 480px)' }}
        onSubmit={event => {
          event.preventDefault();
          void submit('answer');
        }}
      >
        <div className="overlay-title">Command Needs Your Input</div>
        <div className="overlay-body">
          <div
            className="command-display"
            style={{ marginBottom: 'var(--padding-m)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 120, overflowY: 'auto' }}
          >
            {approval.command}
          </div>
          <label
            htmlFor={inputId}
            style={{
              display: 'block',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: 'var(--padding-xs)',
              wordBreak: 'break-word',
            }}
          >
            {prompt}
          </label>
          <input
            id={inputId}
            type={secret ? 'password' : 'text'}
            value={value}
            onChange={event => setValue(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            autoFocus
            disabled={submitting}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: 'var(--padding-s)',
              borderRadius: 'var(--corner-radius-small)',
              border: '1px solid var(--primary)',
              background: 'var(--surface)',
              color: 'var(--text-primary)',
            }}
          />
          {secret && (
            <p style={{ color: 'var(--text-primary)', fontSize: 'var(--font-size-status-small)', marginTop: 'var(--padding-xs)' }}>
              Sent only to this command. Basil does not save or log it.
            </p>
          )}
          {expiry && (
            <p style={{ color: 'var(--text-primary)', fontSize: 'var(--font-size-status-small)', marginTop: 'var(--padding-xs)' }}>
              {`Waiting until ${expiry}`}
            </p>
          )}
          {error && (
            <div
              role="alert"
              style={{
                marginTop: 'var(--padding-m)',
                padding: 'var(--padding-s)',
                borderRadius: 'var(--corner-radius-small)',
                border: '1px solid var(--error-base)',
                color: 'var(--error-base)',
                fontSize: 'var(--font-size-status-small)',
                wordBreak: 'break-word',
              }}
            >
              {error}
            </div>
          )}
        </div>
        <div className="overlay-actions">
          <button type="button" className="action-btn danger" onClick={() => void submit('cancel')} disabled={submitting}>
            Stop Command
          </button>
          <button type="submit" className="action-btn success" disabled={submitting}>
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
