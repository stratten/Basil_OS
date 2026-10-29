import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ChainExpansionMode } from '../../app/chainExpansionPreference';
import {
  pruneExpandedTurns,
  revealRunInExpandedTurns,
  toggleExpandedTurn,
  trimExpandedTurnsForMode,
} from './expandedTurns';

/** Which earlier turns of a chain are open, honoring the single or multiple expansion setting. */
export function useExpandedTurns(mode: ChainExpansionMode, priorRunIds: readonly string[]) {
  const [openedIds, setOpenedIds] = useState<string[]>([]);
  const expandedIds = useMemo(() => pruneExpandedTurns(openedIds, priorRunIds), [openedIds, priorRunIds]);

  // Switching from multiple to single keeps only the most recently opened turn.
  useEffect(() => {
    setOpenedIds(current => {
      const trimmed = trimExpandedTurnsForMode(current, mode);
      return trimmed.length === current.length ? current : trimmed;
    });
  }, [mode]);

  const toggleTurn = useCallback(
    (runId: string) => setOpenedIds(current => toggleExpandedTurn(current, mode, runId)),
    [mode],
  );
  const revealRun = useCallback(
    (runId: string, isPriorRun: boolean) =>
      setOpenedIds(current => revealRunInExpandedTurns(current, mode, runId, isPriorRun)),
    [mode],
  );
  const expandAll = useCallback(() => setOpenedIds([...priorRunIds]), [priorRunIds]);
  const collapseAll = useCallback(() => setOpenedIds([]), []);

  return { expandedIds, toggleTurn, revealRun, expandAll, collapseAll };
}
