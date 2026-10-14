import type { CompanionItem } from './types';

export const LATENCY_SAMPLE_WINDOW = 20;
export const LATENCY_MIN_SAMPLES = 3;

export interface CompanionLatencySummary {
  medianSeconds: number;
  slowSeconds: number;
  sampleCount: number;
}

function nearestRank(sortedAscending: number[], fraction: number): number {
  const rank = Math.ceil(fraction * sortedAscending.length);
  return sortedAscending[Math.min(sortedAscending.length, Math.max(1, rank)) - 1];
}

/** Median and slow (95th percentile) reply time over the most recent stamped items, or null until there are enough samples. */
export function companionLatencySummary(items: CompanionItem[]): CompanionLatencySummary | null {
  const samples = items
    .map((item) => item.latency_ms)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0)
    .slice(-LATENCY_SAMPLE_WINDOW);
  if (samples.length < LATENCY_MIN_SAMPLES) return null;
  const sorted = [...samples].sort((left, right) => left - right);
  return {
    medianSeconds: nearestRank(sorted, 0.5) / 1000,
    slowSeconds: nearestRank(sorted, 0.95) / 1000,
    sampleCount: samples.length,
  };
}

function formatSeconds(seconds: number): string {
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}

export function formatLatencySummary(summary: CompanionLatencySummary): string {
  return `Replies in about ${formatSeconds(summary.medianSeconds)}, slow ones ${formatSeconds(summary.slowSeconds)}`;
}
