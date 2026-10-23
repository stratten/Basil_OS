import type { MouseEvent } from 'react';
import type { StructuredFile } from '../../types';
import { openFile, openContainingFolder, openFilePreviewWindow } from '../../services/bridge';
import { presentFileArtifact } from './fileArtifactPresentation';
import { normalizeFileReference } from './resultContentUtils';
import ExpandableList from '@shared/ExpandableList';
import AttachmentList from '@shared/AttachmentList';
import { pathEntries } from '@shared/attachmentPaths';

// Beyond this many rows (including the Retrieved heading) the list collapses so a long run does not push the rest of the result off screen.
const FILES_COLLAPSED_COUNT = 5;

// The run that produced the files. The preview window uses it to review the file exactly as the side panel does (task snapshots, diffs, history).
export interface FilesTaskContext {
  agentTaskId: string;
  rootTaskId?: string;
}

export function FilesDisplay({ files, taskContext }: { files: StructuredFile[]; resultText: string; taskContext?: FilesTaskContext }) {
  const displayFiles: StructuredFile[] = files.length > 0
    ? files.map(file => normalizeFileReference(file)).filter((file): file is StructuredFile => file !== null)
    : [];

  if (displayFiles.length === 0) return null;

  const changedFiles = displayFiles.filter(file => (file.operation || '').toLowerCase() !== 'read');
  const readFiles = displayFiles.filter(file => (file.operation || '').toLowerCase() === 'read');

  return (
    <div className="result-files">
      <div className="result-files__heading">
        <span className="result-files__heading-text">
          Files:
        </span>
      </div>
      <div className="result-files__list">
        <ExpandableList
          collapsedCount={FILES_COLLAPSED_COUNT}
          contentClassName="result-files__items"
          showAllLabel={total => `Show all ${total} files`}
        >
          {changedFiles.map((file, i) => (
            <FileItemRow key={`changed-${i}`} file={file} taskContext={taskContext} />
          ))}
          {readFiles.length > 0 && (
            <span className={`result-files__retrieved-label${changedFiles.length > 0 ? ' result-files__retrieved--after-changed' : ''}`}>
              Retrieved
            </span>
          )}
          {readFiles.map((file, i) => (
            <FileItemRow key={`read-${i}`} file={file} taskContext={taskContext} />
          ))}
        </ExpandableList>
      </div>
    </div>
  );
}

function FileItemRow({ file, taskContext }: { file: StructuredFile; taskContext?: FilesTaskContext }) {
  const presentation = presentFileArtifact(file);
  const handlePreviewFile = () => {
    console.log(`[FilesDisplay] openFilePreviewWindow requested: name=${file.name} path=${file.path}`);
    openFilePreviewWindow(file.path, taskContext);
  };

  const handleOpenContainingFolder = (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    console.log(`[FilesDisplay] openContainingFolder requested: name=${file.name} path=${file.path}`);
    openContainingFolder(file.path);
  };

  return (
    <div className="result-file-row">
      {/* doc.text.fill — matches Swift's FileItemView icon */}
      <svg className="result-file-row__icon" width="16" height="16" viewBox="0 0 16 16" fill="var(--secondary)">
        <path d="M9.293 0H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4.707A1 1 0 0 0 13.707 4L10 .293A1 1 0 0 0 9.293 0zM9.5 3.5v-2l3 3h-2a1 1 0 0 1-1-1zM5 6h6v1H5V6zm0 2h6v1H5V8zm0 2h3v1H5v-1z"/>
      </svg>
      {presentation.canPreview ? (
        <button
          className="result-file-row__name result-file-row__name--link"
          onClick={handlePreviewFile}
          title={presentation.title}
        >
          {presentation.label}
        </button>
      ) : (
        <span
          className="result-file-row__name"
          title={presentation.title}
        >
          {presentation.label}
        </span>
      )}
      {presentation.canOpenContainingFolder && <button
        className="result-file-row__folder-btn"
        onClick={handleOpenContainingFolder}
        title="Open containing folder"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="var(--text-secondary)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 3.5A1.5 1.5 0 013.5 2h3.172a1.5 1.5 0 011.06.44L9.5 4.2h3A1.5 1.5 0 0114 5.7v6.8a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12.5V3.5z" />
        </svg>
      </button>}
    </div>
  );
}

export function ReferencePathsList({ paths }: { paths: string[] }) {
  return (
    <AttachmentList
      className="attachment-list--inset"
      entries={pathEntries(paths)}
      onOpen={(entry) => openFile(entry.path)}
    />
  );
}
