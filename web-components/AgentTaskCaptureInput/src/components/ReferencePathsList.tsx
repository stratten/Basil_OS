import AttachmentList from '@shared/AttachmentList';
import type { ReferencePathEntry } from '../types';
import { openReferencePath, removeReferencePath } from '../services/bridge';

interface Props {
  paths: ReferencePathEntry[];
}

/** The capture widget's attachment chips: the shared list, flush against the widget's own horizontal padding. App.tsx still owns the whole-window drop overlay and renders this only when references exist. */
export default function ReferencePathsList({ paths }: Props) {
  return (
    <AttachmentList
      className="attachment-list--flush"
      entries={paths.map((entry, index) => ({ key: `${entry.path}-${index}`, path: entry.path, isDirectory: entry.isDirectory }))}
      onOpen={(entry) => openReferencePath(entry.path)}
      onRemove={(_entry, index) => removeReferencePath(index)}
    />
  );
}
