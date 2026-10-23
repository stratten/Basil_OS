/** The outline icon set shared by every Notetaker surface: 16px viewBox, `currentColor`, thin strokes. Sizing comes from the button class that hosts the icon. */

export function RecordCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><circle cx="8" cy="8" r="2.4" fill="currentColor" stroke="none" /></svg>;
}

export function StopCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><rect x="5.5" y="5.5" width="5" height="5" rx=".5" fill="currentColor" stroke="none" /></svg>;
}

export function PlayCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="m6.5 5.3 4.3 2.7-4.3 2.7V5.3Z" fill="currentColor" stroke="none" /></svg>;
}

export function PlusCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M8 5v6M5 8h6" strokeLinecap="round" /></svg>;
}

export function PauseCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M6.6 5.6v4.8M9.4 5.6v4.8" strokeLinecap="round" /></svg>;
}

export function CancelCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="m5.9 5.9 4.2 4.2m0-4.2-4.2 4.2" strokeLinecap="round" /></svg>;
}

export function CopyIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.2" /><path d="M10.5 5.5V3.8A1.3 1.3 0 0 0 9.2 2.5H3.8A1.3 1.3 0 0 0 2.5 3.8v5.4A1.3 1.3 0 0 0 3.8 10.5H5.5" /></svg>;
}

export function CheckIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m3 8.2 3.1 3.1L13 4.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export function CloseIcon() {
  return <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="currentColor" /><path d="m5.8 5.8 4.4 4.4m0-4.4-4.4 4.4" fill="none" stroke="white" strokeWidth="1.2" strokeLinecap="round" /></svg>;
}

export function PinIcon({ filled = false }: { filled?: boolean }) {
  return <svg viewBox="0 0 16 16" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><path d="M9.8 2.2 13.8 6.2l-1.6.8-2.2 2.2.3 2.3-.9.9-2.6-2.6L3 13l-.1-.1 3.4-3.4L3.7 6.9l.9-.9 2.3.3L9.1 4.1l.7-1.9Z" strokeLinejoin="round" /></svg>;
}

export function ThumbUpIcon({ filled = false }: { filled?: boolean }) {
  return <svg viewBox="0 0 16 16" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><path d="M5 7.2 7.4 2.5c.9 0 1.6.7 1.6 1.6V6h3.3a1.2 1.2 0 0 1 1.2 1.4l-.7 4.3a1.5 1.5 0 0 1-1.5 1.3H5V7.2Z" strokeLinejoin="round" /><path d="M2.5 7.2H5V13H2.5V7.2Z" strokeLinejoin="round" /></svg>;
}

export function ThumbDownIcon({ filled = false }: { filled?: boolean }) {
  return <svg viewBox="0 0 16 16" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><path d="M11 8.8 8.6 13.5C7.7 13.5 7 12.8 7 11.9V10H3.7a1.2 1.2 0 0 1-1.2-1.4l.7-4.3A1.5 1.5 0 0 1 4.7 3H11v5.8Z" strokeLinejoin="round" /><path d="M13.5 3H11v5.8h2.5V3Z" strokeLinejoin="round" /></svg>;
}

/** A checked box. The Basil Board draws the same glyph for its To-Dos tab (`checklist` in `BoardChrome.tsx`); change both together. */
export function TodoIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="2.5" y="2.5" width="11" height="11" rx="2.2" /><path d="m5.4 8.2 1.9 1.9 3.4-3.9" /></svg>;
}

/** A friendly robot head: antenna, ears, two eyes and a smile. The Basil Board draws the same glyph for its Agent Tasks tab (`agent_tasks` in `BoardChrome.tsx`); change both together. */
export function AgentTaskIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="5.5" width="10" height="7.5" rx="2.2" /><path d="M8 5.5V3.4M1.8 8.6v2M14.2 8.6v2M6.3 11q1.7 1.1 3.4 0" /><circle cx="8" cy="2.5" r=".9" fill="currentColor" stroke="none" /><circle cx="6" cy="8.5" r=".8" fill="currentColor" stroke="none" /><circle cx="10" cy="8.5" r=".8" fill="currentColor" stroke="none" /></svg>;
}

/** The magnifier the Notetaker already uses for transcript search. */
export function SearchIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="6.8" cy="6.8" r="4.2" /><path d="m10 10 3.2 3.2" strokeLinecap="round" /></svg>;
}
