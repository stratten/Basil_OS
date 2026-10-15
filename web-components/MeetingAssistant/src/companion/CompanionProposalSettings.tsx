import { useState } from 'react';
import MeetingSwitch from '../components/MeetingSwitch';
import type { CompanionAutoProposalAction } from './types';
import type { CompanionGlobalSettingsController } from './useCompanionGlobalSettings';

const AUTO_KINDS: Array<{ action: CompanionAutoProposalAction; label: string }> = [
  { action: 'todo', label: 'Add To-Dos' },
  { action: 'agent_task', label: 'Start Agent Tasks' },
];

/** Whether a watch the user created may start approved kinds of action without a click. Off by default and never chosen for the user. */
export default function CompanionProposalSettings({ settings, update }: Pick<CompanionGlobalSettingsController, 'settings' | 'update'>) {
  const [error, setError] = useState<string | null>(null);

  if (settings === null) return null;

  const save = async (patch: Parameters<typeof update>[0]) => {
    setError(null);
    if (!(await update(patch))) setError('That setting could not be saved.');
  };

  const automatic = settings.proposal_mode === 'auto_execute';
  const chosen = settings.auto_execute_capabilities;

  const toggleKind = (action: CompanionAutoProposalAction, next: boolean) => {
    const rest = chosen.filter((existing) => existing !== action);
    void save({ auto_execute_capabilities: next ? [...rest, action] : rest });
  };

  return (
    <section className="companion-proposal-settings" aria-label="Follow-up actions">
      <h3 className="meeting-section-heading">Follow-up actions</h3>
      <MeetingSwitch
        label="Let my watches start actions without asking"
        checked={automatic}
        onChange={(next) => void save({ proposal_mode: next ? 'auto_execute' : 'suggestion_only' })}
      />
      {automatic && AUTO_KINDS.map(({ action, label }) => (
        <MeetingSwitch key={action} label={label} checked={chosen.includes(action)} onChange={(next) => toggleKind(action, next)} />
      ))}
      <p className="companion-state-note">
        {automatic
          ? chosen.length === 0
            ? 'Choose which kinds of action may start by themselves. Until you do, everything waits for your approval.'
            : 'Only a watch you created can start something, and only for what its wording asks. Everything else waits for your approval.'
          : 'The Companion proposes follow-ups as cards. Nothing starts until you approve it.'}
      </p>
      {error && <p className="meeting-history-load-more-error" role="alert">{error}</p>}
    </section>
  );
}
