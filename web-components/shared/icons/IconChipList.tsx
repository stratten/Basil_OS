import { useState, type ReactNode } from 'react';
import './icon-chip.css';

export interface IconChipEntry {
  key: string;
  name: string;
  /** A qualifier drawn after the name in the warning tone, such as "needs signing in again". Kept apart from the name so the name stays what the person chose. */
  note?: string;
  /** Hover text; defaults to the name. */
  title?: string;
  /** Image sources tried in order. A source that fails to load is skipped, so a server-advertised icon can fall back to a bundled one. */
  iconSources?: readonly string[];
  /** Drawn when there is no source or every source failed. Without it the chip shows the first letter of the name. */
  fallbackIcon?: ReactNode;
  /** Seats the image on a light tile so a dark mark stays legible on a dark appearance. */
  tile?: boolean;
  removeLabel?: string;
  /** Replaces the remove button with a fixed word, such as "Required", for an entry that cannot be removed. */
  lockedLabel?: string;
  /** Free-form tag exposed as data-chip-kind, for hosts and tests that distinguish chip types. */
  kind?: string;
}

export interface IconChipListProps {
  entries: readonly IconChipEntry[];
  /** Omit for a read-only list. */
  onRemove?: (entry: IconChipEntry, index: number) => void;
  removeDisabled?: boolean;
  /** The accessible name of the group. */
  groupLabel: string;
  /** Extra modifier classes on the list. */
  className?: string;
  /** Shown instead of nothing when the list is empty. */
  emptyText?: string;
}

function ChipIcon({ entry }: { entry: IconChipEntry }) {
  const sources = entry.iconSources ?? [];
  const [failedCount, setFailedCount] = useState(0);
  const source = sources[failedCount];
  const className = entry.tile ? 'icon-chip__icon icon-chip__icon--tile' : 'icon-chip__icon';
  if (source) {
    return (
      <span className={className} aria-hidden="true">
        <img className="icon-chip__image" src={source} alt="" onError={() => setFailedCount(count => count + 1)} />
      </span>
    );
  }
  if (entry.fallbackIcon) {
    return <span className={`${className} icon-chip__icon--glyph`} aria-hidden="true">{entry.fallbackIcon}</span>;
  }
  return <span className={`${className} icon-chip__icon--initial`} aria-hidden="true">{entry.name.trim().charAt(0).toUpperCase()}</span>;
}

/** The one icon chip list: a wrapping row of pills, each with an icon, a name, an optional warning note and an optional remove button. Used for excluded apps in Settings and for the connections a scheduled task uses. */
export default function IconChipList({ entries, onRemove, removeDisabled = false, groupLabel, className, emptyText }: IconChipListProps) {
  if (entries.length === 0) {
    return emptyText ? <p className="icon-chip-list__empty">{emptyText}</p> : null;
  }
  return (
    <div className={className ? `icon-chip-list ${className}` : 'icon-chip-list'} role="group" aria-label={groupLabel}>
      {entries.map((entry, index) => (
        <div key={entry.key} className={entry.note ? 'icon-chip has-note' : 'icon-chip'} data-chip-kind={entry.kind} title={entry.title ?? entry.name}>
          <ChipIcon key={(entry.iconSources ?? []).join('\n')} entry={entry} />
          <span className="icon-chip__name">{entry.name}</span>
          {entry.note && <span className="icon-chip__note">{entry.note}</span>}
          {entry.lockedLabel ? (
            <span className="icon-chip__locked">{entry.lockedLabel}</span>
          ) : (
            onRemove && (
              <button
                type="button"
                className="icon-chip__remove"
                disabled={removeDisabled}
                title={entry.removeLabel ?? `Remove ${entry.name}`}
                aria-label={entry.removeLabel ?? `Remove ${entry.name}`}
                onClick={() => onRemove(entry, index)}
              >
                ×
              </button>
            )
          )}
        </div>
      ))}
    </div>
  );
}
