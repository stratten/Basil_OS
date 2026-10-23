import type { ResponseTimeLimit } from '../../types';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Read the backend's `time_limit` object. Anything incomplete yields undefined, so a request from an older backend simply has no countdown. */
export function parseResponseTimeLimit(raw: unknown): ResponseTimeLimit | undefined {
  if (!isRecord(raw)) return undefined;
  const deadlineMs = typeof raw.deadline_at === 'string' ? Date.parse(raw.deadline_at) : Number.NaN;
  const limitSeconds = raw.limit_seconds;
  if (!Number.isFinite(deadlineMs) || typeof limitSeconds !== 'number' || !Number.isFinite(limitSeconds) || limitSeconds <= 0) {
    return undefined;
  }
  return {
    deadlineMs,
    limitSeconds,
    onTimeout: typeof raw.on_timeout === 'string' ? raw.on_timeout : '',
  };
}

/** Read the countdown from an approval's `context`, for both the live event and a recovered pending approval, so the two render alike. */
export function responseTimeLimitFromContext(context: unknown): { time_limit?: ResponseTimeLimit } {
  const timeLimit = isRecord(context) ? parseResponseTimeLimit(context.time_limit) : undefined;
  return timeLimit ? { time_limit: timeLimit } : {};
}

export type ResponseCountdownState = 'running' | 'urgent' | 'expired';

/** Whole seconds left, rounded up so the clock reads 0:00 only once the time is truly up. */
export function secondsUntilDeadline(deadlineMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil((deadlineMs - nowMs) / 1000));
}

/** The last ten seconds, or the last quarter of a wait shorter than forty seconds, read as urgent. */
export function responseCountdownState(secondsLeft: number, limitSeconds: number): ResponseCountdownState {
  if (secondsLeft <= 0) return 'expired';
  return secondsLeft <= Math.min(10, limitSeconds / 4) ? 'urgent' : 'running';
}

export interface ResponseTimeoutSentences {
  /** Said while the clock runs. */
  pending: string;
  /** Said once it reaches zero, until the backend's own resolution replaces the request. */
  expired: string;
}

/** What Basil does at the deadline, in words. */
export function responseTimeoutSentences(onTimeout: string): ResponseTimeoutSentences {
  switch (onTimeout) {
    case 'deny':
      return {
        pending: "If you don't respond, Basil will treat this as declined and carry on.",
        expired: 'Time limit reached. Basil is treating this as declined.',
      };
    case 'deny_and_retry':
      return {
        pending: "If you don't respond, Basil will decline this and try another approach.",
        expired: 'Time limit reached. Basil is declining this and trying another approach.',
      };
    case 'stop_and_ask':
      return {
        pending: "If you don't respond, Basil will stop the command and ask before trying again.",
        expired: 'Time limit reached. Basil is stopping the command.',
      };
    case 'continue_without':
      return {
        pending: "If you don't respond, Basil will carry on without it.",
        expired: 'Time limit reached. Basil is carrying on without it.',
      };
    default:
      return {
        pending: "If you don't respond, Basil will move on.",
        expired: 'Time limit reached. Basil is moving on.',
      };
  }
}
