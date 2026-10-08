import type { MouseEvent } from 'react';
import type { StructuredFile } from '../../types';
import { openFile, openContainingFolder, openFilePreviewWindow } from '../../services/bridge';
import { presentFileArtifact } from './fileArtifactPresentation';
import { normalizeFileReference } from './resultContentUtils';

export function FilesDisplay({ files }: { files: StructuredFile[]; resultText: string }) {
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
        {changedFiles.map((file, i) => (
          <FileItemRow key={`changed-${i}`} file={file} />
        ))}
        {readFiles.length > 0 && (
          <div className={`result-files__retrieved${changedFiles.length > 0 ? ' result-files__retrieved--after-changed' : ''}`}>
            <span className="result-files__retrieved-label">
              Retrieved
            </span>
            {readFiles.map((file, i) => (
              <FileItemRow key={`read-${i}`} file={file} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FileItemRow({ file }: { file: StructuredFile }) {
  const presentation = presentFileArtifact(file);
  const handlePreviewFile = () => {
    console.log(`[FilesDisplay] openFilePreviewWindow requested: name=${file.name} path=${file.path}`);
    openFilePreviewWindow(file.path);
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
  if (paths.length === 0) return null;

  return (
    <div className="result-refs">
      <div className="result-refs__heading">
        <svg width="9" height="9" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M7.775 3.275l1.25-1.25a3.5 3.5 0 1 1 4.95 4.95l-2.5 2.5a3.5 3.5 0 0 1-4.95 0M8.225 12.725l-1.25 1.25a3.5 3.5 0 1 1-4.95-4.95l2.5-2.5a3.5 3.5 0 0 1 4.95 0"/>
        </svg>
        <span className="result-refs__heading-label">
          References
        </span>
      </div>
      {paths.map((p, i) => {
        const name = p.split('/').pop() || p;
        const isDir = p.endsWith('/');
        return (
          <div
            key={i}
            className="result-refs__item"
            onClick={(e) => { e.stopPropagation(); openFile(p); }}
            title={p}
          >
            <svg className="result-refs__item-icon" width="9" height="9" viewBox="0 0 16 16" fill="var(--secondary)" fillOpacity={0.7}>
              {isDir ? (
                <path d="M1 3.5A1.5 1.5 0 012.5 2h3.172a1.5 1.5 0 011.06.44L8.5 4.2h5A1.5 1.5 0 0115 5.7v6.8a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 011 12.5V3.5z"/>
              ) : (
                <path d="M9 0H4a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V5L9 0zm0 1.5V5h3.5L9 1.5zM4 1h4v4.5a.5.5 0 00.5.5H13v8a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z"/>
              )}
            </svg>
            <span className="result-refs__item-name">
              {name}
            </span>
          </div>
        );
      })}
    </div>
  );
}
