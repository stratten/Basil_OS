// Stands in for the number badge of a scheduled check, which has no number. The clock says it came due on a schedule; the turn's label and status stay on the button.
export default function ScheduledCheckGlyph() {
  return (
    <svg className="scheduled-check-glyph" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 4.7v3.6l2.4 1.4" />
    </svg>
  );
}
