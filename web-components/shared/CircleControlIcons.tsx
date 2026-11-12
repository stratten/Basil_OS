/** The outline stop, pause, and play icons that the Notetaker uses for recording controls and that Agent Task windows use for running-task controls. One definition, so the two surfaces always match: 16px viewBox, `currentColor`, thin strokes. Sizing comes from the button class that hosts the icon. `MeetingAssistant/src/components/MeetingIcons.tsx` re-exports these under the same names. */

export function StopCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><rect x="5.5" y="5.5" width="5" height="5" rx=".5" fill="currentColor" stroke="none" /></svg>;
}

export function PlayCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="m6.5 5.3 4.3 2.7-4.3 2.7V5.3Z" fill="currentColor" stroke="none" /></svg>;
}

export function PauseCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M6.6 5.6v4.8M9.4 5.6v4.8" strokeLinecap="round" /></svg>;
}

/** The check circle for deciding yes on an approval or a question. It deliberately differs from the stop circle, because Stop ends the whole task and Deny only refuses one request. */
export function ApproveCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="m5.4 8.2 1.8 1.8 3.4-3.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

/** The arrow circle for carrying on with what the user has entered or chosen. */
export function ContinueCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M5.3 8h5.4M8.6 5.9 10.7 8l-2.1 2.1" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

/** The skip circle, a right-pointing triangle against a vertical bar, for setting a question aside without answering it. The triangle is filled so it reads differently from the outlined arrow of the continue circle. */
export function SkipCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M5.9 5.7v4.6l3.1-2.3z" fill="currentColor" strokeLinejoin="round" /><path d="M10.5 5.8v4.4" strokeLinecap="round" /></svg>;
}

/** The lines circle for looking over the work Basil has done so far. */
export function WorkLogCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M5.6 6.3h4.8M5.6 8h4.8M5.6 9.7h3" strokeLinecap="round" /></svg>;
}

/** The cross circle for refusing one approval or answering no. */
export function DenyCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="m5.9 5.9 4.2 4.2M10.1 5.9 5.9 10.1" strokeLinecap="round" /></svg>;
}
