import { useEffect, useRef } from 'react';
import AttachmentArea from '@shared/AttachmentArea';
import { mergeAttachmentPaths, pathEntries } from '@shared/attachmentPaths';
import { pickFiles, registerFilesPickedHandler } from '../../services/bridge';

interface Props {
  paths: string[];
  onChange: (next: string[]) => void;
}

const SCHEDULED_EMPTY_TEXT = 'Nothing attached yet. Drop files or folders here, or choose Add. Attached items are included as context every time this scheduled task runs.';

// Editable attachments block for the scheduled-task create form and the inline edit form. Dropped paths arrive from Swift's performDragOver/performDragOperation through the same onFilesPicked channel the picker uses, so this component only registers that handler while a form is open (mount and unmount give the exact lifecycle) and the shared drop zone supplies the highlight.
export default function AttachedFilesEditor({ paths, onChange }: Props) {
  // Mirror the latest paths and callback into refs so the single bridge handler, registered once at mount, always merges against the current list without re-registering.
  const pathsRef = useRef(paths);
  useEffect(() => { pathsRef.current = paths; }, [paths]);
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  // The bridge's registry is single-callback; the returned unregister only clears it while this editor still owns it.
  useEffect(() => registerFilesPickedHandler((picked) => {
    const merged = mergeAttachmentPaths(pathsRef.current, picked);
    if (merged.length === pathsRef.current.length) return;
    onChangeRef.current(merged);
  }), []);

  return (
    <AttachmentArea
      entries={pathEntries(paths)}
      canEdit
      emptyText={SCHEDULED_EMPTY_TEXT}
      onPick={() => pickFiles()}
      onRemove={(_entry, index) => onChange(paths.filter((_, itemIndex) => itemIndex !== index))}
    />
  );
}
