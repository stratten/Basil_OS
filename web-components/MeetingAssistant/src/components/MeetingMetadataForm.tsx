import { memo, useEffect, useState } from 'react';
import { updateMetadata } from '../bridge/meetingBridge';

interface MeetingMetadataFormProps {
  name: string;
  purpose: string;
  participants: string;
  isViewingPastMeeting: boolean;
}

/**
 * Debounces edits (400ms of no keystrokes) before sending `updateMetadata`,
 * so Swift is not flooded on every keystroke. Local input value is kept in
 * component state; when a fresh snapshot's value differs from the last
 * value this component itself sent, the local field re-syncs to the
 * incoming value (this only happens on meeting switch or an out-of-band
 * native edit, never during the user's own typing turn).
 */
function MeetingMetadataForm({ name, purpose, participants, isViewingPastMeeting }: MeetingMetadataFormProps) {
  const [localName, setLocalName] = useState(name);
  const [localPurpose, setLocalPurpose] = useState(purpose);
  const [localParticipants, setLocalParticipants] = useState(participants);
  const [participantDraft, setParticipantDraft] = useState('');

  useEffect(() => setLocalName(name), [name]);
  useEffect(() => setLocalPurpose(purpose), [purpose]);
  useEffect(() => {
    setLocalParticipants(participants);
    setParticipantDraft('');
  }, [participants]);

  useEffect(() => {
    if (localName === name) return;
    const handle = setTimeout(() => updateMetadata({ name: localName }), 400);
    return () => clearTimeout(handle);
  }, [localName, name]);

  useEffect(() => {
    if (localPurpose === purpose) return;
    const handle = setTimeout(() => updateMetadata({ purpose: localPurpose }), 400);
    return () => clearTimeout(handle);
  }, [localPurpose, purpose]);

  useEffect(() => {
    if (localParticipants === participants) return;
    const handle = setTimeout(() => updateMetadata({ participants: localParticipants }), 400);
    return () => clearTimeout(handle);
  }, [localParticipants, participants]);

  const participantTokens = parseParticipants(localParticipants);
  const commitParticipantDraft = () => {
    const additions = parseParticipants(participantDraft);
    if (additions.length === 0) return;
    const seen = new Set(participantTokens.map((token) => token.toLocaleLowerCase()));
    const next = [...participantTokens];
    for (const addition of additions) {
      const key = addition.toLocaleLowerCase();
      if (!seen.has(key)) {
        seen.add(key);
        next.push(addition);
      }
    }
    setLocalParticipants(next.join(', '));
    setParticipantDraft('');
  };

  const removeParticipant = (index: number) => {
    setLocalParticipants(participantTokens.filter((_, tokenIndex) => tokenIndex !== index).join(', '));
  };

  return (
    <section className="meeting-metadata-section" aria-labelledby="meeting-information-heading">
      <div className="meeting-section-heading-row">
        <h2 id="meeting-information-heading" className="meeting-section-heading">Meeting Information</h2>
        {isViewingPastMeeting && <span className="meeting-past-meeting-badge">Viewing Past Meeting</span>}
      </div>
      <div className="meeting-metadata-form">
        <input
          type="text"
          className="meeting-metadata-name-input"
          value={localName}
          placeholder="Meeting Name"
          onChange={(event) => setLocalName(event.target.value)}
        />
        <input
          type="text"
          className="meeting-metadata-purpose-input"
          value={localPurpose}
          placeholder="Purpose (optional)"
          onChange={(event) => setLocalPurpose(event.target.value)}
        />
        <div className="meeting-participant-field">
          {participantTokens.map((token, index) => (
            <span key={`${token}-${index}`} className="meeting-participant-chip">
              <span>{token}</span>
                <button type="button" aria-label={`Remove ${token}`} onClick={() => removeParticipant(index)}>
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <circle cx="8" cy="8" r="6" />
                    <path d="m5.8 5.8 4.4 4.4m0-4.4-4.4 4.4" fill="none" stroke="white" strokeWidth="1.2" strokeLinecap="round" />
                  </svg>
                </button>
            </span>
          ))}
          <input
              type="text"
              className="meeting-participant-draft"
              value={participantDraft}
              placeholder={participantTokens.length === 0 ? 'Participants (comma separated)' : 'Add participant'}
              onChange={(event) => {
                const next = event.target.value;
                setParticipantDraft(next);
                if (next.includes(',')) {
                  const complete = next.slice(0, next.lastIndexOf(',') + 1);
                  const remainder = next.slice(next.lastIndexOf(',') + 1);
                  const additions = parseParticipants(complete);
                  const seen = new Set(participantTokens.map((token) => token.toLocaleLowerCase()));
                  setLocalParticipants([...participantTokens, ...additions.filter((token) => {
                    const key = token.toLocaleLowerCase();
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                  })].join(', '));
                  setParticipantDraft(remainder.trimStart());
                }
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  commitParticipantDraft();
                }
              }}
              onBlur={commitParticipantDraft}
            />
        </div>
      </div>
    </section>
  );
}

export default memo(MeetingMetadataForm);

function parseParticipants(value: string): string[] {
  return value.split(',').map((token) => token.trim()).filter(Boolean);
}
