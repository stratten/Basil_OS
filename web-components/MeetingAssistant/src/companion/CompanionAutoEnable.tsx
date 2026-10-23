import { useState } from 'react';
import MeetingSwitch from '../components/MeetingSwitch';
import type { CompanionGlobalSettingsController } from './useCompanionGlobalSettings';

/** The global "turn on for every new meeting" preference. */
export default function CompanionAutoEnable({ settings, update }: Pick<CompanionGlobalSettingsController, 'settings' | 'update'>) {
  const [error, setError] = useState<string | null>(null);

  if (settings === null) return null;

  const change = async (next: boolean) => {
    setError(null);
    const saved = await update({ auto_enable: next });
    if (!saved) setError('That setting could not be saved.');
  };

  return (
    <div className="companion-auto-enable">
      <MeetingSwitch label="Turn on for every new meeting" checked={settings.auto_enable} onChange={(next) => void change(next)} />
      {error && <p className="meeting-history-load-more-error" role="alert">{error}</p>}
    </div>
  );
}
