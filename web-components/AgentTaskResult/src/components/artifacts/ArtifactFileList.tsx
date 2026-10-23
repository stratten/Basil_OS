import { useMemo, useState } from 'react';
import ExpandableList from '@shared/ExpandableList';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';
import { classifyArtifactFileType } from './artifactFileType';
import {
  ARTIFACT_SORT_KEYS,
  nextArtifactSort,
  sortArtifacts,
  type ArtifactSortKey,
  type ArtifactSortState,
} from './artifactSort';
import { formatHistoryTimestamp } from '../../app/dateDisplay';
import { FileTypeIcon } from './FileTypeIcon';

/** Rows shown before the rest sit behind "Show all". Kept small so the preview below keeps most of the panel; the last row fades to show there is more. */
const COLLAPSED_COUNT = 2;

const SORT_LABELS: Record<ArtifactSortKey, string> = { name: 'Name', modified: 'Modified', type: 'Type' };
/** Characters kept visible after the ellipsis, so the end of a long name (usually its extension) is never cut. */
const NAME_TAIL_LENGTH = 10;
const NAME_SPLIT_THRESHOLD = 18;

/** Splits a long name so the head can truncate with an ellipsis while the tail stays visible. */
function splitFileName(name: string): { head: string; tail: string } {
  if (name.length <= NAME_SPLIT_THRESHOLD) return { head: name, tail: '' };
  return { head: name.slice(0, -NAME_TAIL_LENGTH), tail: name.slice(-NAME_TAIL_LENGTH) };
}

export interface ArtifactFileListProps {
  artifacts: DerivedAgentTaskArtifact[];
  activeArtifactId: string;
  onSelectArtifact: (artifactId: string) => void;
}

/**
 * The documents a run produced, one per row with a type icon, sortable by name, modified time, or type. Each row shows the exact time the agent last touched the file (always the absolute form, independent of the history date setting, so it matches what the Modified sort orders by). The default order is the run's own, and the sort lasts as long as the list stays mounted.
 */
export function ArtifactFileList({ artifacts, activeArtifactId, onSelectArtifact }: ArtifactFileListProps) {
  const [sort, setSort] = useState<ArtifactSortState>(null);

  const sorted = useMemo(() => sortArtifacts(artifacts, sort), [artifacts, sort]);
  const activeIndex = sorted.findIndex(artifact => artifact.artifactId === activeArtifactId);

  return (
    <div className="artifact-file-list">
      <div className="artifact-file-list__header">
        <span className="artifact-file-list__title">Documents ({artifacts.length})</span>
        {artifacts.length > 1 && (
          <div className="artifact-file-list__sort" role="group" aria-label="Sort documents">
            {ARTIFACT_SORT_KEYS.map(key => {
              const isActive = sort?.key === key;
              const direction = isActive ? sort.direction : undefined;
              return (
                <button
                  key={key}
                  type="button"
                  className={`artifact-file-list__sort-button${isActive ? ' is-active' : ''}`}
                  aria-pressed={isActive}
                  aria-label={`Sort by ${SORT_LABELS[key].toLowerCase()}${direction ? `, ${direction === 'asc' ? 'ascending' : 'descending'}` : ''}`}
                  onClick={() => setSort(current => nextArtifactSort(current, key))}
                >
                  {SORT_LABELS[key]}
                  {direction && <span className="artifact-file-list__sort-arrow" aria-hidden="true">{direction === 'asc' ? '\u2191' : '\u2193'}</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <ExpandableList
        collapsedCount={COLLAPSED_COUNT}
        fadeCollapsed
        keepVisibleIndex={activeIndex >= 0 ? activeIndex : undefined}
        contentClassName="artifact-file-list__rows"
        contentRole="tablist"
        contentAriaLabel="Documents produced this turn"
        showAllLabel={total => `Show all ${total} documents`}
      >
        {sorted.map(artifact => {
          const type = classifyArtifactFileType(artifact);
          const { head, tail } = splitFileName(artifact.displayName);
          const touchedLabel = formatHistoryTimestamp(artifact.lastTouchedAt, 'absolute');
          const isActive = artifact.artifactId === activeArtifactId;
          return (
            <button
              key={artifact.artifactId}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`artifact-file-row${isActive ? ' is-active' : ''}`}
              onClick={() => onSelectArtifact(artifact.artifactId)}
              data-tooltip={artifact.displayName}
              data-tooltip-when="truncated"
            >
              <span className="artifact-file-row__icon" title={type.label}>
                <FileTypeIcon category={type.category} />
              </span>
              <span className="artifact-file-row__name">
                <span className="artifact-file-row__name-head">{head}</span>
                {tail && <span className="artifact-file-row__name-tail">{tail}</span>}
              </span>
              {artifact.review && artifact.review.revisionCount > 1 && (
                <span className="artifact-file-row__badge">v{artifact.review.revisionCount}</span>
              )}
              {touchedLabel && (
                <span className="artifact-file-row__time">{touchedLabel}</span>
              )}
            </button>
          );
        })}
      </ExpandableList>
    </div>
  );
}
