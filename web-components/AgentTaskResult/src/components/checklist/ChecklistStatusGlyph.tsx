import type { ChecklistStatus } from '../../services/checklistApi';
import { CHECKLIST_STATUS_LABEL } from './checklistPresentation';

/** One mark per state, drawn in `currentColor` so the stylesheet's status roles (amber for your turn, green for done) tint it. */
export default function ChecklistStatusGlyph({ status }: { status: ChecklistStatus }) {
  return (
    <svg
      className={`checklist-glyph checklist-glyph--${status}`}
      viewBox="0 0 16 16"
      role="img"
      aria-label={CHECKLIST_STATUS_LABEL[status]}
    >
      {status === 'pending' && <circle cx="8" cy="8" r="5.5" />}
      {status === 'in_progress' && (
        <>
          <circle cx="8" cy="8" r="5.5" />
          <path className="checklist-glyph__fill" d="M8 2.5a5.5 5.5 0 0 1 0 11z" />
        </>
      )}
      {status === 'waiting_user' && (
        <>
          <circle className="checklist-glyph__fill" cx="8" cy="8" r="6" />
          <path className="checklist-glyph__mark" d="M8 4.8v3.9M8 11v.2" />
        </>
      )}
      {status === 'waiting_external' && (
        <>
          <circle cx="8" cy="8" r="5.5" />
          <path d="M8 5v3.2l2 1.4" />
        </>
      )}
      {status === 'done' && (
        <>
          <circle className="checklist-glyph__fill" cx="8" cy="8" r="6" />
          <path className="checklist-glyph__mark" d="m5.2 8.2 2 2 3.6-4" />
        </>
      )}
      {status === 'dropped' && (
        <>
          <circle cx="8" cy="8" r="5.5" />
          <path d="M5.5 10.5l5-5" />
        </>
      )}
    </svg>
  );
}
