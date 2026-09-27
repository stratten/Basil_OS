import type { CSSProperties } from 'react';
import { openContainingFolder, openFile } from '../../services/bridge';
import { pathBasename } from './scheduledAgentTaskHelpers';

interface Props {
  paths: string[];
}

// Read-only renderer for the Attached Files list shown in the scheduled
// AgentTask detail view's display mode (i.e. when not editing). Each row is a
// clickable link that opens the file via the Swift bridge, plus a small
// Reveal-in-Finder affordance — same interaction pattern as the capture
// widget's reference list (see ResultContent.tsx's ReferencePathsList).
//
// Encapsulates the surrounding "Files" meta row (label + container) so the
// caller can drop this in alongside the other meta rows (Schedule / Status /
// Next run) with a single line. Renders nothing when the list is empty so
// callers don't need a guard wrapper.
//
// Visual NOTE: the inline `metaRow*Style` objects intentionally duplicate the
// values of the same-named locals in ScheduledAgentTaskDetail. Keep them in
// sync if the parent's meta-row styling ever changes; lifting them into a
// shared module is overkill for two call sites today, but worth doing if a
// third meta row ever needs them.
export default function AttachedFilesDisplay({ paths }: Props) {
  if (!Array.isArray(paths) || paths.length === 0) return null;

  const metaRowStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 8,
    fontFamily: 'var(--font-family-light)',
    fontSize: 'var(--font-size-callout)',
    color: 'var(--text-secondary)',
    lineHeight: 1.4,
  };
  const metaLabelStyle: CSSProperties = {
    fontFamily: 'var(--font-family-medium)',
    color: 'var(--text-tertiary)',
    minWidth: 72,
  };

  return (
    <div style={metaRowStyle}>
      <span style={metaLabelStyle}>Files</span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, flex: 1 }}>
        {paths.map((path, idx) => {
          // Mirror ResultContent's reference list / capture widget:
          // basename rendered as an underlined primary link that
          // opens the file via the native bridge, with a secondary
          // Reveal-in-Finder affordance to jump straight to the
          // containing folder. Trailing-slash heuristic picks the
          // folder icon (paths the picker emits for directories
          // typically end in '/'); plain files get the document
          // icon. Both icons inherit the same secondary tint as
          // the capture widget.
          const isDir = path.endsWith('/');
          return (
            <div
              key={`${path}-${idx}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                minWidth: 0,
              }}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  openFile(path);
                }}
                title={path}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  margin: 0,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  minWidth: 0,
                  flex: 1,
                  cursor: 'pointer',
                  textAlign: 'left',
                  color: 'inherit',
                  font: 'inherit',
                }}
              >
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 16 16"
                  fill="var(--secondary)"
                  fillOpacity={0.7}
                  style={{ flexShrink: 0 }}
                >
                  {isDir ? (
                    <path d="M1 3.5A1.5 1.5 0 012.5 2h3.172a1.5 1.5 0 011.06.44L8.5 4.2h5A1.5 1.5 0 0115 5.7v6.8a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 011 12.5V3.5z" />
                  ) : (
                    <path d="M9 0H4a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V5L9 0zm0 1.5V5h3.5L9 1.5zM4 1h4v4.5a.5.5 0 00.5.5H13v8a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" />
                  )}
                </svg>
                <span
                  style={{
                    fontFamily: 'var(--font-family-medium)',
                    color: 'var(--primary)',
                    textDecoration: 'underline',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    minWidth: 0,
                  }}
                >
                  {pathBasename(path)}
                </span>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  openContainingFolder(path);
                }}
                title="Reveal in Finder"
                aria-label={`Reveal ${pathBasename(path)} in Finder`}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 2,
                  cursor: 'pointer',
                  flexShrink: 0,
                  lineHeight: 0,
                  color: 'var(--text-tertiary)',
                }}
              >
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M2 4.5A1.5 1.5 0 013.5 3h3l1.5 1.5h4.5A1.5 1.5 0 0114 6v6.5A1.5 1.5 0 0112.5 14h-9A1.5 1.5 0 012 12.5v-8z" />
                </svg>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
