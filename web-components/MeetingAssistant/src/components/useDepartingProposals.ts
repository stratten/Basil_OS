import { useEffect, useRef, useState } from 'react';
import type { MeetingActionProposalDTO } from '../bridge/types';

/** How long a card that was just handled holds its confirmation before it starts to leave. */
export const DEPARTURE_CONFIRM_MS = 450;

/** How long the fade and the slide-up take. Matches the transition on `.meeting-proposal-card.is-departing-leave` in meeting-proposal-motion.css. */
export const DEPARTURE_LEAVE_MS = 450;

/** When the card finally moves to its group: the confirmation, the exit and a short margin so the exit has visibly finished. */
export const DEPARTURE_TOTAL_MS = DEPARTURE_CONFIRM_MS + DEPARTURE_LEAVE_MS + 50;

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function sameMembers(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  return left.size === right.size && Array.from(left).every((id) => right.has(id));
}

/**
 * The ids of proposals that just left the active list (added to To-Dos, started, or dismissed) and are still playing their exit.
 *
 * A card that leaves the active list is moved to a group at the bottom the moment its status changes, which snaps everything below it upward. The caller keeps rendering a departing card in the active list until its exit has finished, then lets it move. Nothing departs on the first render, for cards that were never shown as active, or under reduced motion.
 */
export function useDepartingProposals(
  proposals: MeetingActionProposalDTO[],
  isActive: (proposal: MeetingActionProposalDTO) => boolean,
): ReadonlySet<string> {
  const activeIds = proposals.filter(isActive).map((proposal) => proposal.id);
  const activeKey = activeIds.join('\u0000');
  const [previous, setPrevious] = useState({ key: activeKey, ids: activeIds });
  const [departing, setDeparting] = useState<ReadonlySet<string>>(() => new Set());
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // Derived while rendering, so a departing card is never drawn once in its new group before it is brought back.
  if (previous.key !== activeKey) {
    setPrevious({ key: activeKey, ids: activeIds });
    const nowActive = new Set(activeIds);
    const stillKnown = new Set(proposals.map((proposal) => proposal.id));
    const next = new Set(Array.from(departing).filter((id) => !nowActive.has(id)));
    if (!prefersReducedMotion()) {
      for (const id of previous.ids) if (!nowActive.has(id) && stillKnown.has(id)) next.add(id);
    }
    if (!sameMembers(next, departing)) setDeparting(next);
  }

  useEffect(() => {
    for (const [id, timer] of Array.from(timers.current)) {
      if (departing.has(id)) continue;
      clearTimeout(timer);
      timers.current.delete(id);
    }
    for (const id of departing) {
      if (timers.current.has(id)) continue;
      timers.current.set(id, setTimeout(() => {
        timers.current.delete(id);
        setDeparting((existing) => {
          if (!existing.has(id)) return existing;
          const remaining = new Set(existing);
          remaining.delete(id);
          return remaining;
        });
      }, DEPARTURE_TOTAL_MS));
    }
  }, [departing]);

  useEffect(() => () => {
    timers.current.forEach((timer) => clearTimeout(timer));
    timers.current.clear();
  }, []);

  return departing;
}
