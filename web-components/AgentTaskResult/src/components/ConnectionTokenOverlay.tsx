import { useEffect, useMemo, useState } from 'react';
import type { TokenConnectRequest } from '../types';
import { agentStore } from '../store/agentStore';
import {
  registerTokenConnectResultHandler,
  requestTokenConnect,
  requestTokenConnectCancel,
} from '../services/bridge';

export const MAX_CONNECTION_NAME_LENGTH = 80;
export const MAX_CONNECTION_DESCRIPTION_LENGTH = 500;

const fieldStyle = {
  width: '100%',
  boxSizing: 'border-box',
  padding: 'var(--padding-s)',
  borderRadius: 'var(--corner-radius-small)',
  border: '1px solid var(--primary)',
  background: 'var(--surface)',
  color: 'var(--text-primary)',
} as const;

const labelStyle = {
  display: 'block',
  fontWeight: 600,
  color: 'var(--text-primary)',
  marginBottom: 'var(--padding-xs)',
  wordBreak: 'break-word',
} as const;

const hintStyle = {
  color: 'var(--text-primary)',
  fontSize: 'var(--font-size-status-small)',
  marginTop: 'var(--padding-xs)',
} as const;

export function nameProblem(name: string, existingNames: string[]): string | null {
  const trimmed = name.trim();
  if (!trimmed) return 'Give this connection a name.';
  if (trimmed.length > MAX_CONNECTION_NAME_LENGTH) return `Use ${MAX_CONNECTION_NAME_LENGTH} characters or fewer.`;
  if (existingNames.some(existing => existing.localeCompare(trimmed, undefined, { sensitivity: 'accent' }) === 0)) {
    return `A connection named ${trimmed} already exists. Choose a different name, such as adding the account or purpose.`;
  }
  return null;
}

interface Props {
  agentTaskId: string;
  request: TokenConnectRequest;
}

export default function ConnectionTokenOverlay({ agentTaskId, request }: Props) {
  const [name, setName] = useState(request.friendlyName);
  const [description, setDescription] = useState(request.description ?? '');
  const [token, setToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = useMemo(() => nameProblem(name, request.existingNames), [name, request.existingNames]);
  const canSubmit = !submitting && problem === null && token.trim().length > 0;

  useEffect(() => {
    return registerTokenConnectResultHandler(result => {
      if (result.requestId !== request.requestId) return;
      if (result.status === 'failed') {
        setSubmitting(false);
        setError(result.message || 'The Basil app could not finish the connection.');
        return;
      }
      setToken('');
      agentStore.hideTokenConnect(agentTaskId, request.requestId);
    });
  }, [agentTaskId, request.requestId]);

  const submit = () => {
    if (!canSubmit) return;
    const trimmedDescription = description.trim();
    setSubmitting(true);
    setError(null);
    requestTokenConnect({
      requestId: request.requestId,
      friendlyName: name.trim(),
      description: trimmedDescription ? trimmedDescription.slice(0, MAX_CONNECTION_DESCRIPTION_LENGTH) : undefined,
      token,
    });
  };

  const cancel = () => {
    if (submitting) return;
    requestTokenConnectCancel(request.requestId);
  };

  return (
    <div className="overlay-backdrop">
      <form
        className="overlay-card"
        aria-label="Connect a service with a token"
        data-agent-desk-interactive-overlay="true"
        data-preferred-content-width={480}
        style={{ maxWidth: 'clamp(360px, 60vw, 480px)' }}
        onSubmit={event => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="overlay-title">Connect a service with a token</div>
        <div className="overlay-body">
          <p style={{ margin: `0 0 var(--padding-m)` }}>
            Basil will send this token only to the host below. The assistant never sees it, and it is not written to the chat.
          </p>
          <p style={{ fontWeight: 600, margin: `0 0 var(--padding-xs)` }}>Basil will send the token only to</p>
          <p style={{ margin: 0, wordBreak: 'break-word' }}>{request.host}</p>
          <p style={{ margin: `0 0 var(--padding-m)`, wordBreak: 'break-word', fontSize: 'var(--font-size-status-small)' }}>
            {request.serverUrl}
          </p>
          {request.alreadyConnectedAs ? (
            <p role="status" style={{ margin: `0 0 var(--padding-m)` }}>
              {`You already have ${request.alreadyConnectedAs} connected at this address. This adds a second connection, for example another account or workspace, so give it a name that tells them apart.`}
            </p>
          ) : null}
          <label htmlFor={`token-connect-name-${request.requestId}`} style={labelStyle}>
            Name
          </label>
          <input
            id={`token-connect-name-${request.requestId}`}
            type="text"
            aria-label="Connection name"
            placeholder="For example Hugging Face (work)"
            value={name}
            disabled={submitting}
            autoComplete="off"
            spellCheck={false}
            onChange={event => setName(event.target.value)}
            style={{ ...fieldStyle, marginBottom: 'var(--padding-s)' }}
          />
          {problem && (name.trim() || request.alreadyConnectedAs) ? (
            <p role="alert" style={{ ...hintStyle, color: 'var(--error-base)', marginBottom: 'var(--padding-s)' }}>
              {problem}
            </p>
          ) : null}
          <label htmlFor={`token-connect-description-${request.requestId}`} style={labelStyle}>
            Description (optional)
          </label>
          <input
            id={`token-connect-description-${request.requestId}`}
            type="text"
            aria-label="Connection description"
            placeholder="What this connection is for"
            value={description}
            disabled={submitting}
            autoComplete="off"
            spellCheck={false}
            onChange={event => setDescription(event.target.value)}
            style={{ ...fieldStyle, marginBottom: 'var(--padding-xs)' }}
          />
          <p style={{ ...hintStyle, marginBottom: 'var(--padding-m)' }}>
            Shown in Settings and read by the agent, so it can choose the right connection when you have several for one service.
          </p>
          <label htmlFor={`token-connect-token-${request.requestId}`} style={labelStyle}>
            Token or API key
          </label>
          <input
            id={`token-connect-token-${request.requestId}`}
            type="password"
            aria-label="Token or API key"
            placeholder="Paste the token here"
            value={token}
            disabled={submitting}
            autoComplete="off"
            spellCheck={false}
            autoFocus
            onChange={event => setToken(event.target.value)}
            style={fieldStyle}
          />
          <p style={hintStyle}>
            Sent only to this host. Basil does not write it to the chat or show it to the assistant.
          </p>
          {submitting ? (
            <p role="status" style={{ ...hintStyle, marginTop: 'var(--padding-s)' }}>
              {`Checking the token with ${request.host}…`}
            </p>
          ) : null}
          {error ? (
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
          ) : null}
        </div>
        <div className="overlay-actions">
          <button type="button" className="action-btn danger" onClick={cancel} disabled={submitting}>
            Cancel
          </button>
          <button type="submit" className="action-btn success" disabled={!canSubmit}>
            Connect
          </button>
        </div>
      </form>
    </div>
  );
}
