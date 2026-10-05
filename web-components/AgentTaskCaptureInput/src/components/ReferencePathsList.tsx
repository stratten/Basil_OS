import type { ReferencePathEntry } from '../types';
import { openReferencePath, removeReferencePath } from '../services/bridge';

interface Props {
  paths: ReferencePathEntry[];
}

function basename(path: string): string {
  const trimmed = path.endsWith('/') ? path.slice(0, -1) : path;
  return trimmed.split('/').pop() || trimmed;
}

function FolderGlyph() {
  return (
    <svg width="9" height="9" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M1 4a1 1 0 0 1 1-1h4l1.5 2H14a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V4Z" />
    </svg>
  );
}

function DocGlyph() {
  return (
    <svg width="9" height="9" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M3 1h6l4 4v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1Z" />
      <path d="M9 1v4h4" fill="none" stroke="var(--background-secondary)" strokeWidth="0.8" />
    </svg>
  );
}

export default function ReferencePathsList({ paths }: Props) {
  return (
    <div className="reference-paths-list">
      <div className="reference-paths-list__header">
        <svg width="9" height="9" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
        </svg>
        <span>References</span>
      </div>
      <div className="reference-paths-list__rows">
        {paths.map((entry, index) => (
          <div key={`${entry.path}-${index}`} className="reference-paths-list__row">
            <span className="reference-paths-list__row-icon" style={{ color: 'color-mix(in srgb, var(--secondary) 70%, transparent)' }}>
              {entry.isDirectory ? <FolderGlyph /> : <DocGlyph />}
            </span>
            <button
              type="button"
              className="reference-paths-list__row-name"
              onClick={() => openReferencePath(entry.path)}
              data-tooltip={entry.path}
            >
              {basename(entry.path)}
            </button>
            <button
              type="button"
              className="reference-paths-list__row-remove"
              onClick={() => removeReferencePath(index)}
              aria-label={`Remove ${basename(entry.path)}`}
              title={`Remove ${basename(entry.path)}`}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
