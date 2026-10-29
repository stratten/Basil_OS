import AttachmentList from '@shared/AttachmentList';
import { pathEntries } from '@shared/attachmentPaths';
import { openContainingFolder, openFile } from '../../services/bridge';

interface Props {
  paths: string[];
}

// Read-only list of the files attached to a scheduled task, shown in the detail view's display mode. Each name opens the file through the Swift bridge and each row has a Reveal in Finder button, the same chips as every other attachments list. Renders nothing when empty so callers need no guard.
export default function AttachedFilesDisplay({ paths }: Props) {
  if (!Array.isArray(paths) || paths.length === 0) return null;
  return (
    <AttachmentList
      className="attachment-list--inset"
      entries={pathEntries(paths)}
      onOpen={(entry) => openFile(entry.path)}
      onReveal={(entry) => openContainingFolder(entry.path)}
    />
  );
}
