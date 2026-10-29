import type { StructuredFile } from '../../types';

export interface FileArtifactPresentation {
  label: string;
  title: string;
  canPreview: boolean;
  canOpenContainingFolder: boolean;
}

function displayPath(path: string): string {
  return path || 'Unknown path';
}

function operationLabel(operation: string | undefined): string {
  switch (operation?.toLowerCase()) {
    case 'create':
      return 'Created';
    case 'copy':
      return 'Copied';
    case 'delete':
      return 'Deleted';
    case 'move':
      return 'Moved';
    case 'rename':
      return 'Renamed';
    case 'update':
    case 'write':
      return 'Updated';
    case 'read':
    case 'retrieve':
    case 'retrieved':
      return 'Retrieved';
    default:
      return '';
  }
}

function operationPathLabel(file: StructuredFile, operation: string | undefined, label: string): string {
  if (operation === 'copy' || operation === 'move' || operation === 'rename') {
    return `${label}: ${displayPath(file.sourcePath ?? '')} → ${displayPath(file.path)}`;
  }

  return label ? `${label}: ${file.name}` : file.name;
}

export function presentFileArtifact(file: StructuredFile): FileArtifactPresentation {
  const operation = file.operation?.toLowerCase();
  const isDeleted = operation === 'delete';
  const isDirectory = file.kind === 'directory';
  const label = operationLabel(operation);
  const display = operationPathLabel(file, operation, label);

  return {
    label: display,
    title: isDeleted ? `Deleted ${file.path}` : isDirectory ? `Open ${file.path}` : `Preview ${file.path}`,
    canPreview: !isDeleted && !isDirectory,
    canOpenContainingFolder: !isDeleted,
  };
}
