import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import NativeSymbolIcon from '../../../shared/NativeSymbolIcon';
import { pickCompanionFolder, subscribeFilesDropped } from '../bridge/meetingBridge';
import { CloseIcon } from '../components/MeetingIcons';
import type { CompanionRoot } from './types';

export const DROP_ARM_EXPIRY_MS = 3000;

interface CompanionSourcesProps {
  roots: CompanionRoot[];
  pendingRoots: string[];
  canEdit: boolean;
  onAddPaths: (paths: string[]) => Promise<void>;
  onRemoveRoot: (rootId: string) => Promise<boolean>;
  onRemovePending: (path: string) => void;
}

export default function CompanionSources({ roots, pendingRoots, canEdit, onAddPaths, onRemoveRoot, onRemovePending }: CompanionSourcesProps) {
  const armedRef = useRef(false);
  const expiryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isOver, setIsOver] = useState(false);

  const arm = useCallback(() => {
    armedRef.current = true;
    if (expiryRef.current) clearTimeout(expiryRef.current);
    expiryRef.current = setTimeout(() => {
      armedRef.current = false;
    }, DROP_ARM_EXPIRY_MS);
  }, []);

  const disarm = useCallback(() => {
    armedRef.current = false;
    if (expiryRef.current) clearTimeout(expiryRef.current);
    expiryRef.current = null;
  }, []);

  useEffect(() => {
    if (!canEdit) return undefined;
    const unsubscribe = subscribeFilesDropped(({ paths, source }) => {
      if (source !== 'picker' && !armedRef.current) return;
      disarm();
      setIsOver(false);
      void onAddPaths(paths);
    });
    return () => {
      unsubscribe();
      disarm();
    };
  }, [canEdit, disarm, onAddPaths]);

  const handleDrag = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    arm();
    setIsOver(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
    disarm();
    setIsOver(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    // Stops WebKit from navigating to the dropped file; the paths themselves arrive through the native callback.
    event.preventDefault();
    setIsOver(false);
  };

  if (!canEdit && roots.length === 0) return null;

  return (
    <section className="companion-sources" aria-label="Context sources">
      <h3 className="meeting-section-heading">Context</h3>
      {canEdit && (
        <div
          className={`companion-drop-zone${isOver ? ' is-over' : ''}`}
          data-testid="companion-drop-zone"
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <p>Drop a folder or file here to ground the Companion in it.</p>
          <button type="button" className="meeting-record-button" onClick={pickCompanionFolder}>
            <NativeSymbolIcon name="folder" />
            Choose…
          </button>
        </div>
      )}
      {(roots.length > 0 || pendingRoots.length > 0) && (
        <ul className="companion-chip-list">
          {roots.map((root) => (
            <li key={root.id} className="meeting-participant-chip" title={`${root.kind === 'folder' ? 'Folder' : 'File'}: ${root.path}`}>
              <NativeSymbolIcon name={root.kind === 'folder' ? 'folder' : 'openFile'} size={12} />
              <span className="companion-chip-name">{root.display_name}</span>
              {canEdit && (
                <button type="button" aria-label={`Remove ${root.display_name}`} onClick={() => void onRemoveRoot(root.id)}>
                  <CloseIcon />
                </button>
              )}
            </li>
          ))}
          {pendingRoots.map((path) => (
            <li key={path} className="meeting-participant-chip is-pending" title={`Queued until the Companion is on: ${path}`}>
              <NativeSymbolIcon name="folder" size={12} />
              <span className="companion-chip-name">{path.split('/').filter(Boolean).pop() ?? path}</span>
              <button type="button" aria-label={`Remove queued ${path}`} onClick={() => onRemovePending(path)}>
                <CloseIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
