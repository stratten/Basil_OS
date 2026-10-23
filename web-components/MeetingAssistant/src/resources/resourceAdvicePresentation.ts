import type { ResourceAdvice } from './resourceAdviceTypes';

/** How long the condition has held, in words: "just now", "for 3 min", "for 1 h 5 min". */
export function formatAdviceDuration(raisedAtSeconds: number, nowMilliseconds: number): string {
  const elapsedSeconds = Math.max(0, Math.floor(nowMilliseconds / 1000 - raisedAtSeconds));
  if (elapsedSeconds < 60) return 'just now';
  const minutes = Math.floor(elapsedSeconds / 60);
  if (minutes < 60) return `for ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `for ${hours} h` : `for ${hours} h ${rest} min`;
}

/** The chip label: the most severe advice, with a count of the rest. */
export function adviceChipLabel(advice: ResourceAdvice[]): string {
  if (advice.length === 0) return '';
  const extra = advice.length - 1;
  return extra === 0 ? advice[0].title : `${advice[0].title} and ${extra} more`;
}

export function mostSevere(advice: ResourceAdvice[]): ResourceAdvice['severity'] {
  if (advice.some((item) => item.severity === 'critical')) return 'critical';
  if (advice.some((item) => item.severity === 'warning')) return 'warning';
  return 'info';
}
