import { useState } from 'react';
import { formatClockSeconds } from '@shared/formatClockSeconds';
import { CloseIcon, PlusCircleIcon } from '../components/MeetingIcons';
import type { CompanionWatch } from './types';

interface CompanionWatchesProps {
  watches: CompanionWatch[];
  canEdit: boolean;
  onCreate: (topic: string, instruction: string) => Promise<boolean>;
  onCancel: (watchId: string) => Promise<boolean>;
}

export default function CompanionWatches({ watches, canEdit, onCreate, onCancel }: CompanionWatchesProps) {
  const [topic, setTopic] = useState('');
  const [instruction, setInstruction] = useState('');
  const [saving, setSaving] = useState(false);
  const active = watches.filter((watch) => watch.active);

  if (!canEdit && active.length === 0) return null;

  const submit = async () => {
    const trimmedTopic = topic.trim();
    if (trimmedTopic === '' || saving) return;
    setSaving(true);
    const created = await onCreate(trimmedTopic, instruction.trim());
    setSaving(false);
    if (created) {
      setTopic('');
      setInstruction('');
    }
  };

  return (
    <section className="companion-watches" aria-label="Standing watches">
      <h3 className="meeting-section-heading">Watching for</h3>
      {active.length === 0 && <p className="companion-state-note">Nothing yet. Ask for something to be surfaced whenever a topic comes up.</p>}
      {active.length > 0 && (
        <ul className="companion-watch-list">
          {active.map((watch) => (
            <li key={watch.id} className="companion-watch">
              <div className="companion-watch-copy">
                <span className="companion-item-kind">{watch.topic}</span>
                {watch.instruction !== '' && <span className="meeting-status-message companion-wrap">{watch.instruction}</span>}
                {watch.last_triggered_at !== null && <span className="meeting-status-message">Last surfaced at [{formatClockSeconds(watch.last_triggered_at, { padMinutes: true })}]</span>}
              </div>
              {canEdit && (
                <button type="button" className="meeting-transcript-icon-button" aria-label={`Stop watching ${watch.topic}`} title="Stop watching" onClick={() => void onCancel(watch.id)}>
                  <CloseIcon />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form
          className="companion-watch-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <input className="meeting-metadata-name-input" aria-label="Watch topic" placeholder="Topic, for example billing" value={topic} maxLength={200} onChange={(event) => setTopic(event.target.value)} />
          <input className="meeting-metadata-name-input" aria-label="What to surface" placeholder="What to surface (optional)" value={instruction} maxLength={600} onChange={(event) => setInstruction(event.target.value)} />
          <button type="submit" className="meeting-record-button" disabled={saving || topic.trim() === ''}>
            <PlusCircleIcon />
            {saving ? 'Adding…' : 'Add Watch'}
          </button>
        </form>
      )}
    </section>
  );
}
