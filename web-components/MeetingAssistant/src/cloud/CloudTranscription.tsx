import { useEffect, useId, useState } from 'react';
import MeetingSwitch from '../components/MeetingSwitch';
import { chipLabel, chipTone, fallbackNotice } from './cloudTranscriptionPresentation';
import { MIN_API_KEY_LENGTH, type CloudConnection, type CloudProviderId, type CloudTranscriptionState } from './cloudTranscriptionTypes';
import { useCloudTranscription } from './useCloudTranscription';

export interface CloudTranscriptionProps {
  port: number;
}

const DISCLOSURE =
  'While this is on, live meeting audio is sent to the service you choose so it can be transcribed. Basil still keeps the full recording on this Mac, and the local model takes over if the service stops. The service is billed by its provider under its own terms. Nothing is sent unless you turn this on.';

/** A chip that shows whether live transcription is running in the cloud, with the opt-in, provider and key setup in a panel. */
export default function CloudTranscription({ port }: CloudTranscriptionProps) {
  const cloud = useCloudTranscription(port);
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const { state } = cloud;

  if (port <= 0) return null;
  const tone = chipTone(state);

  return (
    <div
      className="meeting-cloud"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && open) {
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        className={`meeting-cloud-chip meeting-cloud-chip--${tone}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="meeting-cloud-dot" aria-hidden="true" />
        <span className="meeting-cloud-chip-label">{chipLabel(state)}</span>
      </button>
      {open && (
        <div id={panelId} className="meeting-cloud-panel" role="group" aria-label="Cloud transcription settings">
          {state === null ? (
            <div className="meeting-cloud-section">
              <p className="meeting-status-message" role={cloud.loadError === null ? 'status' : 'alert'}>
                {cloud.loadError ?? 'Loading cloud transcription settings.'}
              </p>
              {cloud.loadError !== null && (
                <button type="button" className="meeting-record-button" onClick={() => void cloud.retry()}>
                  Try Again
                </button>
              )}
            </div>
          ) : (
            <CloudSettings cloud={cloud} state={state} panelId={panelId} />
          )}
        </div>
      )}
    </div>
  );
}

type CloudController = ReturnType<typeof useCloudTranscription>;

function CloudSettings({ cloud, state, panelId }: { cloud: CloudController; state: CloudTranscriptionState; panelId: string }) {
  const [understood, setUnderstood] = useState(false);
  const [keyDraft, setKeyDraft] = useState('');
  const selected = state.providers.find((provider) => provider.id === state.provider) ?? state.providers[0];
  const ownKey = state.connection === 'own_key';
  const notice = fallbackNotice(state.status);
  const needsDisclosure = !state.acknowledged && !understood;

  useEffect(() => {
    setKeyDraft('');
  }, [state.provider, state.connection]);

  const chooseConnection = (connection: CloudConnection) => {
    void cloud.update({ connection });
  };
  const chooseProvider = (provider: CloudProviderId) => {
    void cloud.update({ provider });
  };
  const saveKey = async () => {
    if (await cloud.saveKey(selected.id, keyDraft.trim())) setKeyDraft('');
  };

  return (
    <>
      <p className="meeting-cloud-disclosure">{DISCLOSURE}</p>
      {!state.acknowledged && (
        <label className="meeting-cloud-acknowledge">
          <input type="checkbox" checked={understood} onChange={(event) => setUnderstood(event.target.checked)} />
          I understand that live meeting audio will be sent to the service I choose.
        </label>
      )}
      <fieldset className="meeting-cloud-section" disabled={cloud.busy}>
        <legend>Connection</legend>
        <label>
          <input type="radio" name={`${panelId}-connection`} checked={ownKey} onChange={() => chooseConnection('own_key')} />
          My own API key (words appear as people speak)
        </label>
        <label>
          <input type="radio" name={`${panelId}-connection`} checked={!ownKey} onChange={() => chooseConnection('basil_account')} />
          My Basil account (updates every few seconds)
        </label>
        {!ownKey && !state.account_available && <p className="meeting-status-message">Sign in to Basil to use your account.</p>}
      </fieldset>
      {ownKey && (
        <fieldset className="meeting-cloud-section" disabled={cloud.busy}>
          <legend>Service</legend>
          {state.providers.map((provider) => (
            <label key={provider.id}>
              <input type="radio" name={`${panelId}-provider`} checked={provider.id === state.provider} onChange={() => chooseProvider(provider.id)} />
              {provider.label}
              {provider.has_key ? ' (key saved)' : ''}
            </label>
          ))}
          <div className="meeting-cloud-key-row">
            <input
              className="meeting-metadata-name-input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              aria-label={`${selected.label} API key`}
              placeholder={selected.has_key ? 'Enter a new key to replace the saved one' : 'Paste your API key'}
              value={keyDraft}
              maxLength={512}
              onChange={(event) => setKeyDraft(event.target.value)}
            />
            <button type="button" className="meeting-record-button" disabled={keyDraft.trim().length < MIN_API_KEY_LENGTH} onClick={() => void saveKey()}>
              Save Key
            </button>
          </div>
          <div className="meeting-cloud-key-row">
            <button type="button" className="meeting-record-button" disabled={!selected.has_key} onClick={() => void cloud.check(selected.id)}>
              Test Connection
            </button>
            <button type="button" className="meeting-record-button" disabled={!selected.has_key} onClick={() => void cloud.removeKey(selected.id)}>
              Remove Key
            </button>
          </div>
          {cloud.checkResult !== null && (
            <p className={cloud.checkResult.ok ? 'meeting-status-message' : 'meeting-history-load-more-error'} role="status">
              {cloud.checkResult.message}
            </p>
          )}
        </fieldset>
      )}
      <MeetingSwitch
        label="Use cloud transcription"
        checked={state.enabled}
        disabled={cloud.busy || (!state.enabled && needsDisclosure)}
        onChange={(enabled) => void cloud.update({ enabled, ...(enabled && understood ? { acknowledge_disclosure: true } : {}) })}
      />
      {!state.enabled && needsDisclosure && <p className="meeting-status-message">Confirm the statement above to turn this on.</p>}
      {notice !== null && (
        <p className="meeting-history-load-more-error" role="status">
          {notice}
        </p>
      )}
      {cloud.actionError !== null && (
        <p className="meeting-history-load-more-error" role="alert">
          {cloud.actionError}
        </p>
      )}
    </>
  );
}
