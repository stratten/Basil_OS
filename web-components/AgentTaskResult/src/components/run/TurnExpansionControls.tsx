import type { ChainExpansionMode } from '../../app/chainExpansionPreference';

interface Props {
  mode: ChainExpansionMode;
  priorTurnCount: number;
  expandedCount: number;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

// Outward chevrons mean expand all and inward chevrons mean collapse all, matching the Swavigator title bar.
function ExpandAllGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="4 6 8 2 12 6" />
      <polyline points="4 10 8 14 12 10" />
    </svg>
  );
}

function CollapseAllGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="4 2 8 6 12 2" />
      <polyline points="4 14 8 10 12 14" />
    </svg>
  );
}

/**
 * Expand all and collapse all for the earlier turns of a chain.
 * Single mode can only ever show one open turn, so it offers just a collapse button while one is open.
 */
export function TurnExpansionControls({ mode, priorTurnCount, expandedCount, onExpandAll, onCollapseAll }: Props) {
  if (priorTurnCount === 0) return null;
  const showExpandAll = mode === 'multiple';
  if (!showExpandAll && expandedCount === 0) return null;
  return (
    <div className="turn-expansion-controls" role="group" aria-label="Earlier turns">
      {showExpandAll && (
        <button
          type="button"
          className="turn-expansion-button"
          title="Expand all earlier turns"
          aria-label="Expand all earlier turns"
          disabled={expandedCount >= priorTurnCount}
          onClick={onExpandAll}
        >
          <ExpandAllGlyph />
        </button>
      )}
      <button
        type="button"
        className="turn-expansion-button"
        title="Collapse all earlier turns"
        aria-label="Collapse all earlier turns"
        disabled={expandedCount === 0}
        onClick={onCollapseAll}
      >
        <CollapseAllGlyph />
      </button>
    </div>
  );
}
