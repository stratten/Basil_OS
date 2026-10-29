import type { ChainExpansionMode } from '../../app/chainExpansionPreference';

// Earlier turns of a chain are listed in the order they were opened, so "most recent" is the last entry.

/** Drops ids that are no longer earlier turns of the displayed task, keeping the opening order. */
export function pruneExpandedTurns(expandedIds: readonly string[], priorRunIds: readonly string[]): string[] {
  return expandedIds.filter(id => priorRunIds.includes(id));
}

/** Single mode keeps only the most recently opened turn; multiple mode keeps everything. */
export function trimExpandedTurnsForMode(expandedIds: readonly string[], mode: ChainExpansionMode): string[] {
  if (mode === 'multiple' || expandedIds.length <= 1) return [...expandedIds];
  return expandedIds.slice(-1);
}

export function toggleExpandedTurn(
  expandedIds: readonly string[],
  mode: ChainExpansionMode,
  runId: string,
): string[] {
  if (expandedIds.includes(runId)) return expandedIds.filter(id => id !== runId);
  return mode === 'multiple' ? [...expandedIds, runId] : [runId];
}

/**
 * Whether the turn list already shows what a navigation to `runId` needs.
 * Single mode shows exactly the destination (or nothing, when the destination is the current run).
 * Multiple mode only requires the destination itself to be open, and never closes other turns.
 */
export function isRunRevealed(
  expandedIds: readonly string[],
  mode: ChainExpansionMode,
  runId: string,
  isPriorRun: boolean,
): boolean {
  if (mode === 'multiple') return !isPriorRun || expandedIds.includes(runId);
  if (!isPriorRun) return expandedIds.length === 0;
  return expandedIds.length === 1 && expandedIds[0] === runId;
}

/** The expanded list after revealing `runId`; the inverse check of `isRunRevealed`. */
export function revealRunInExpandedTurns(
  expandedIds: readonly string[],
  mode: ChainExpansionMode,
  runId: string,
  isPriorRun: boolean,
): string[] {
  if (mode === 'multiple') {
    if (!isPriorRun || expandedIds.includes(runId)) return [...expandedIds];
    return [...expandedIds, runId];
  }
  return isPriorRun ? [runId] : [];
}
