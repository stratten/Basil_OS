import { useEffect, useRef, useState } from 'react';
import { pickFiles, registerFilesPickedHandler } from '../../services/bridge';
import { pathBasename } from './scheduledAgentTaskHelpers';

interface Props {
  paths: string[];
  onChange: (next: string[]) => void;
}

// Editable Attached Files block rendered inside the create form and the
// inline-edit form in ScheduledAgentTaskDetail. Each row shows the basename +
// dim full path + Remove button; an "Add file…" button at the bottom invokes
// the native picker bridge; the whole container is a drop target for
// files/folders dragged from Finder (paths are delivered by Swift's
// performDragOperation override through the same onFilesPicked channel).
//
// Owns its `isDragging` flag and the picker-handler registration entirely:
// because this component is mounted only while a form is open, mount/unmount
// give us the exact "register only while a form is open" lifecycle that
// previously lived in the parent's `formOpen`-keyed effect. Sibling consumers
// (e.g. TextFollowUp) re-register their own handler on their own mount, so
// the bridge's "last writer wins" pattern continues to work cleanly when the
// user navigates between views.
export default function AttachedFilesEditor({ paths, onChange }: Props) {
  const [isDragging, setIsDragging] = useState(false);

  // Mirror the latest `paths` into a ref so the picker callback (registered
  // once at mount, see effect below) can dedupe against the *current* list
  // without having to re-register on every paths change. Without this the
  // callback would close over the initial empty array and back-to-back picks
  // would never grow past the first batch.
  const pathsRef = useRef(paths);
  useEffect(() => { pathsRef.current = paths; }, [paths]);

  // Stable ref to onChange too, so we don't tear down + re-register the
  // bridge handler whenever the parent passes a fresh callback identity.
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  useEffect(() => {
    registerFilesPickedHandler((picked) => {
      const seen = new Set(pathsRef.current);
      const additions = picked.filter(p => typeof p === 'string' && p && !seen.has(p));
      if (additions.length === 0) return;
      onChangeRef.current([...pathsRef.current, ...additions]);
    });
    return () => {
      // Reset to a no-op rather than removing entirely; the bridge's
      // registry is single-callback, so leaving it pointed at a no-op
      // matches the "no consumer mounted" baseline state.
      registerFilesPickedHandler(() => {});
    };
  }, []);

  const removeAt = (idx: number) => {
    onChange(paths.filter((_, i) => i !== idx));
  };

  return (
    <div
      onDragOver={(e) => {
        // preventDefault is required for WebKit to fire the drop event at
        // all. stopPropagation keeps the parent form (which doesn't accept
        // drops itself) from receiving a redundant event.
        e.preventDefault();
        e.stopPropagation();
        if (!isDragging) setIsDragging(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
      }}
      onDrop={(e) => {
        // We deliberately do NOT read paths from ``e.dataTransfer.files``:
        // WKWebView (unlike Electron) does not populate the non-standard
        // ``File.path`` property, so absolute paths are unreachable from
        // JS. Instead, ``AgentTaskResultWebView``'s ``performDragOperation``
        // override reads the file URLs from the AppKit pasteboard and
        // forwards them through ``window.basilAgentTask.onFilesPicked`` —
        // the same channel ``pickFiles()`` uses, which the picker effect
        // above is already listening on. The only thing this handler
        // needs to do is clear the drop-target highlight; preventDefault
        // keeps WebKit from doing any default drop handling on top of that.
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
      }}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        padding: 8,
        border: isDragging
          ? '2px solid var(--secondary)'
          : '1px solid var(--separator-color)',
        // Compensate the +1px border so layout doesn't jiggle on drag-over.
        margin: isDragging ? -1 : 0,
        borderRadius: 6,
        background: 'var(--background-tertiary)',
        position: 'relative',
        transition: 'border-color 0.12s ease-out',
      }}
    >
      {isDragging && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: 6,
            background: 'rgba(0,48,135,0.12)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10,
            pointerEvents: 'none',
          }}
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 16 16"
            fill="none"
            stroke="var(--secondary)"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M8 10V2M5 5l3-3 3 3" />
            <path d="M2 10v3a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3" />
          </svg>
          <span
            style={{
              fontFamily: 'var(--font-family-medium)',
              fontSize: 'var(--font-size-status-tiny)',
              color: 'var(--secondary)',
              marginTop: 4,
            }}
          >
            Drop files here
          </span>
        </div>
      )}
      <div
        style={{
          fontFamily: 'var(--font-family-medium)',
          fontSize: 'var(--font-size-status-small)',
          color: 'var(--text-tertiary)',
        }}
      >
        Attached files
      </div>
      {paths.length === 0 ? (
        <div
          style={{
            fontFamily: 'var(--font-family-light)',
            fontSize: 'var(--font-size-status-small)',
            color: 'var(--text-secondary)',
          }}
        >
          No files attached. Add one below to include it as context every time
          this scheduled task runs.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {paths.map((path, idx) => (
            <div
              key={`${path}-${idx}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '4px 6px',
                border: '1px solid var(--separator-color)',
                borderRadius: 'var(--corner-radius-small)',
                background: 'var(--background-secondary)',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
                <span
                  style={{
                    fontFamily: 'var(--font-family-medium)',
                    fontSize: 'var(--font-size-status-small)',
                    color: 'var(--text-primary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={path}
                >
                  {pathBasename(path)}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--font-family-light)',
                    fontSize: 'var(--font-size-status-tiny)',
                    color: 'var(--text-tertiary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {path}
                </span>
              </div>
              <button
                type="button"
                className="action-btn"
                onClick={() => removeAt(idx)}
                aria-label={`Remove ${pathBasename(path)}`}
                title="Remove from this scheduled task"
                style={{ padding: '2px 8px', flexShrink: 0 }}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          type="button"
          className="action-btn"
          onClick={() => pickFiles()}
          title="Open the system file picker to add a file or folder"
        >
          Add file…
        </button>
      </div>
    </div>
  );
}
