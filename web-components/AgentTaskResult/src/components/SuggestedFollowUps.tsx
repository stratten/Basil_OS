import { requestFollowUpLineAdded, requestFollowUpLineRemoved, useFollowUpDraft } from '../store/followUpPrefillStore';
import { hasDraftLine } from './followUpDraftLines';

interface SuggestedFollowUpsProps {
  /** Chain root the follow-up box belongs to. */
  taskKey: string;
  suggestions: readonly string[] | undefined;
}

/** Offers the verifier's suggested next requests. Each chip toggles its own line in the follow-up box, so several can be combined and edited before anything is sent. A chip shows as picked while its line is in the box, so deleting the line by hand unpicks it. */
export function SuggestedFollowUps({ taskKey, suggestions }: SuggestedFollowUpsProps) {
  const draft = useFollowUpDraft(taskKey);
  if (!suggestions || suggestions.length === 0) return null;
  return (
    <div className="suggested-follow-ups" role="group" aria-label="Suggested follow-ups" data-testid="suggested-follow-ups">
      {suggestions.map(text => {
        const picked = hasDraftLine(draft, text);
        return (
          <button
            key={text}
            type="button"
            className={`suggested-follow-up-chip${picked ? ' suggested-follow-up-chip--picked' : ''}`}
            aria-pressed={picked}
            title={picked
              ? 'Remove this from the follow-up box'
              : 'Add this to the follow-up box. Pick several to combine them, and edit before sending'}
            onClick={() => (picked ? requestFollowUpLineRemoved(taskKey, text) : requestFollowUpLineAdded(taskKey, text))}
          >
            <span className="suggested-follow-up-check" aria-hidden="true">✓</span>
            {text}
          </button>
        );
      })}
    </div>
  );
}
