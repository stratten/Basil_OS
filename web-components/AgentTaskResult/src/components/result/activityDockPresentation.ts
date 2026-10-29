import type { ProgressStep, TimelineEntry } from '../../types';
import { selectActivityTrail } from './activityPresentation';

export type ActivityDisclosure = 'collapsed' | 'trail' | 'full';
export type ActivityDisclosureAction = 'toggleTrail' | 'showFull' | 'showLess' | 'collapse';

export function nextActivityDisclosure(
  current: ActivityDisclosure,
  action: ActivityDisclosureAction,
): ActivityDisclosure {
  if (action === 'toggleTrail') return current === 'collapsed' ? 'trail' : 'collapsed';
  if (action === 'showFull') return current === 'trail' ? 'full' : current;
  if (action === 'showLess') return current === 'full' ? 'trail' : current;
  return 'collapsed';
}

export function readableActivityCount(timeline: TimelineEntry[]): number {
  return selectActivityTrail(timeline, 0).length;
}

export function hasVisibleActivity(timeline: TimelineEntry[], steps: ProgressStep[]): boolean {
  return readableActivityCount(timeline) > 0 || steps.length > 0;
}

export function selectFallbackActivityTrail(
  steps: ProgressStep[],
  limit = 3,
): ProgressStep[] {
  return limit > 0 ? steps.slice(-limit) : steps;
}
