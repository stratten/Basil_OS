import { useCallback, useEffect, useMemo, useRef } from 'react';
import AttachmentArea from '../../../shared/AttachmentArea';
import type { AttachmentEntry } from '../../../shared/attachmentPaths';
import { pickCompanionFolder, subscribeFilesDropped } from '../bridge/meetingBridge';
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
      void onAddPaths(paths);
    });
    return () => {
      unsubscribe();
      disarm();
    };
  }, [canEdit, disarm, onAddPaths]);

  const entries = useMemo<AttachmentEntry[]>(
    () => [
      ...roots.map((root) => ({
        key: root.id,
        path: root.path,
        name: root.display_name,
        isDirectory: root.kind === 'folder',
        title: `${root.kind === 'folder' ? 'Folder' : 'File'}: ${root.path}`,
        removeLabel: `Remove ${root.display_name}`,
      })),
      ...pendingRoots.map((path) => ({
        key: `pending:${path}`,
        path,
        pending: true,
        title: `Queued until the Companion is on: ${path}`,
        removeLabel: `Remove queued ${path}`,
      })),
    ],
    [roots, pendingRoots],
  );

  const handleRemove = useCallback(
    (entry: AttachmentEntry) => {
      if (entry.pending) onRemovePending(entry.path);
      else void onRemoveRoot(entry.key);
    },
    [onRemovePending, onRemoveRoot],
  );

  if (!canEdit && roots.length === 0) return null;

  return (
    <AttachmentArea
      className="companion-sources"
      titleClassName="meeting-section-heading"
      zoneTestId="companion-drop-zone"
      entries={entries}
      canEdit={canEdit}
      onPick={pickCompanionFolder}
      onArm={arm}
      onDisarm={disarm}
      disarmOnDrop={false}
      onRemove={handleRemove}
    />
  );
}
