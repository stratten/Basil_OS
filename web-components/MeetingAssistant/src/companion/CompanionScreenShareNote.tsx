import { useState } from 'react';
import { CheckIcon } from '../components/MeetingIcons';
import type { CompanionGlobalSettingsController } from './useCompanionGlobalSettings';

/** First-use note about screen sharing; dismissal is the global Companion setting `screen_share_note_dismissed`. */
export default function CompanionScreenShareNote({ settings, update }: Pick<CompanionGlobalSettingsController, 'settings' | 'update'>) {
  const [error, setError] = useState<string | null>(null);

  if (settings === null || settings.screen_share_note_dismissed !== false) return null;

  const dismiss = async () => {
    setError(null);
    const saved = await update({ screen_share_note_dismissed: true });
    if (!saved) setError('That could not be saved, so this note will appear again.');
  };

  return (
    <div className="companion-notice" role="note">
      <p><strong>Sharing your screen?</strong> You may want to share a single window or close the companion first.</p>
      <button type="button" className="meeting-record-button" onClick={() => void dismiss()}>
        <CheckIcon />
        Got it
      </button>
      {error && <p className="meeting-history-load-more-error" role="alert">{error}</p>}
    </div>
  );
}
