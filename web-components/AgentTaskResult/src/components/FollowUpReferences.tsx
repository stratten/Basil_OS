import AttachmentList from '../../../shared/AttachmentList';
import { pathEntries } from '../../../shared/attachmentPaths';

interface Props {
  paths: string[];
  onRemove: (index: number) => void;
}

/** The files and folders attached to a follow-up or run note, each removable before it is sent. */
export default function FollowUpReferences({ paths, onRemove }: Props) {
  return (
    <AttachmentList
      className="text-followup-references attachment-list--inset"
      entries={pathEntries(paths)}
      onRemove={(_entry, index) => onRemove(index)}
    />
  );
}
