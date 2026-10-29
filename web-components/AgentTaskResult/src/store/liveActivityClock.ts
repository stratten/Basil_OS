// Remembers, per task, when the last live event arrived and where the live feed went dark. A dropped WebSocket loses progress events for good, so after it reconnects the durable timeline is merged back in, but only from the moment the feed was lost. Kept outside the reactive store because it changes on every event and nothing renders from it.

const lastLiveEventAtMs = new Map<string, number>();
const liveGapStartMs = new Map<string, number>();

export function noteLiveEvent(agentTaskId: string, nowMs: number = Date.now()): void {
  lastLiveEventAtMs.set(agentTaskId, nowMs);
}

/** Opens a gap for every task that has received live events and does not already have one open. */
export function markLiveFeedLost(): void {
  for (const [agentTaskId, lastEventAt] of lastLiveEventAtMs) {
    if (!liveGapStartMs.has(agentTaskId)) liveGapStartMs.set(agentTaskId, lastEventAt);
  }
}

/** When live events stopped arriving for this task, or undefined when the feed has not been interrupted. */
export function liveGapStart(agentTaskId: string): number | undefined {
  return liveGapStartMs.get(agentTaskId);
}

export function clearLiveGap(agentTaskId: string): void {
  liveGapStartMs.delete(agentTaskId);
}

export function forgetLiveActivity(agentTaskId: string): void {
  lastLiveEventAtMs.delete(agentTaskId);
  liveGapStartMs.delete(agentTaskId);
}

export function resetLiveActivityClockForTests(): void {
  lastLiveEventAtMs.clear();
  liveGapStartMs.clear();
}
