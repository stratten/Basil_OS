import { useState, type ComponentType } from 'react';
import { AgentTaskIcon, SearchIcon, TodoIcon } from '../components/MeetingIcons';
import type { CompanionItemAction, CompanionItemActionResult } from './types';

const ACTIONS: ReadonlyArray<{ action: CompanionItemAction; label: string; hint: string; busy: string; Icon: ComponentType }> = [
  { action: 'todo', label: 'Make to-do', hint: 'Add this to your To-Do list', busy: 'Adding to your To-Do list…', Icon: TodoIcon },
  { action: 'agent_task', label: 'Hand to agent', hint: 'Send this to an agent as a task', busy: 'Sending to an agent…', Icon: AgentTaskIcon },
];

interface CompanionActionButtonsProps {
  /** Which of Make to-do and Hand to agent to offer; none offers neither. */
  allowedActions: readonly CompanionItemAction[];
  onAction: (action: CompanionItemAction) => Promise<CompanionItemActionResult | null>;
  /** Given when Investigate is on offer for this note or finding. */
  onInvestigate?: () => void;
}

/** The note and finding actions as icon buttons that sit in the same row as pin, copy and the rest. The icons are the Basil Board's own To-Do and Agent Tasks glyphs and the Notetaker's magnifier; the tooltip says what each one does. Investigate stays with the Companion's own controls on the left; Make to-do and Hand to agent hand the note to another part of Basil, so they sit apart at the right end of the row. Renders a fragment so the buttons are direct children of the row. */
export default function CompanionActionButtons({ allowedActions, onAction, onInvestigate }: CompanionActionButtonsProps) {
  const [acting, setActing] = useState<CompanionItemAction | null>(null);

  const act = async (action: CompanionItemAction) => {
    if (acting !== null) return;
    setActing(action);
    await onAction(action);
    setActing(null);
  };

  const offered = ACTIONS.filter((entry) => allowedActions.includes(entry.action));

  return (
    <>
      {onInvestigate !== undefined && (
        <button type="button" className="meeting-transcript-icon-button" aria-label="Investigate" title="Investigate: look this up in your sources" onClick={onInvestigate}>
          <SearchIcon />
        </button>
      )}
      {offered.length > 0 && (
        <span className="companion-item-actions-end">
          {offered.map(({ action, label, hint, busy, Icon }) => (
            <button
              key={action}
              type="button"
              className="meeting-transcript-icon-button"
              aria-label={label}
              aria-busy={acting === action}
              title={acting === action ? busy : `${label}: ${hint}`}
              disabled={acting !== null}
              onClick={() => void act(action)}
            >
              <Icon />
            </button>
          ))}
        </span>
      )}
    </>
  );
}
