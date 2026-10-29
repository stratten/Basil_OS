import { useEffect, useRef, useState } from 'react';
import type { DisplayableAgentTask } from '../../types';

/** Silence shorter than this is normal model latency and is not worth calling out. */
export const QUIET_NOTICE_AFTER_SECONDS = 30;

/** Changes whenever anything a person could watch changes: a new step, more result text, more reasoning. */
export function activitySignature(agentTask: DisplayableAgentTask): string {
  const timeline = agentTask.executionTimeline ?? [];
  const lastEntry = timeline[timeline.length - 1];
  const reasoningLength = (agentTask.thinkingSegments ?? []).reduce((total, segment) => total + (segment.text?.length ?? 0), 0)
    + (agentTask.thinking?.length ?? 0);
  return [
    timeline.length,
    lastEntry?.id ?? '',
    agentTask.progressSteps?.length ?? 0,
    agentTask.currentStep ?? '',
    agentTask.result?.length ?? 0,
    reasoningLength,
  ].join('|');
}

/** "No new activity for 45s" or "No new activity for 2m 05s". */
export function formatQuietNotice(quietSeconds: number): string {
  const whole = Math.max(0, Math.floor(quietSeconds));
  if (whole < 60) return `No new activity for ${whole}s`;
  const minutes = Math.floor(whole / 60);
  const seconds = String(whole % 60).padStart(2, '0');
  return `No new activity for ${minutes}m ${seconds}s`;
}

/**
 * Whole seconds since the signature last changed while `active`, or 0 until the silence is long enough to mention.
 * State only changes once the threshold is crossed, so a healthy run does not re-render every second.
 */
export function useQuietSeconds(active: boolean, signature: string): number {
  const [quietSeconds, setQuietSeconds] = useState(0);
  const lastChangeAtMs = useRef(Date.now());

  useEffect(() => {
    lastChangeAtMs.current = Date.now();
    setQuietSeconds(0);
  }, [signature, active]);

  useEffect(() => {
    if (!active) return undefined;
    const interval = setInterval(() => {
      const quiet = Math.floor((Date.now() - lastChangeAtMs.current) / 1000);
      setQuietSeconds(quiet >= QUIET_NOTICE_AFTER_SECONDS ? quiet : 0);
    }, 1000);
    return () => clearInterval(interval);
  }, [active]);

  return active ? quietSeconds : 0;
}
