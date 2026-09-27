import type { StructuredFile } from '../../types';

export function parseResult(result: string): { technicalSteps: string; userSummary: string } {
  const lines = result.split('\n');
  const technicalLines: string[] = [];
  const summaryLines: string[] = [];
  let inTechnicalSection = false;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith('STEP_START:') ||
        trimmed.startsWith('STEP_COMPLETE:') ||
        trimmed.startsWith('FAIL_NOTE:')) {
      technicalLines.push(line);
      inTechnicalSection = true;
    } else if (inTechnicalSection && trimmed === '') {
      technicalLines.push(line);
    } else if (inTechnicalSection && trimmed !== '' &&
               !trimmed.startsWith('STEP_START:') &&
               !trimmed.startsWith('STEP_COMPLETE:') &&
               !trimmed.startsWith('FAIL_NOTE:')) {
      inTechnicalSection = false;
      summaryLines.push(line);
    } else if (!inTechnicalSection) {
      summaryLines.push(line);
    }
  }

  const technical = technicalLines.join('\n').trim();
  const summary = summaryLines.join('\n').trim();

  return { technicalSteps: technical, userSummary: summary || result };
}

export function normalizeResultForPresentation(result: string, outcome?: string): string {
  if (outcome?.trim().toLowerCase() !== 'completed_with_warnings') return result;
  return result.replace(/^Completed with warnings:\s*/i, '');
}

export interface ExtractedFile {
  name: string;
  path: string;
}

export type FileReference = StructuredFile & {
  full_path?: string;
  fullPath?: string;
  file_path?: string;
  filePath?: string;
  source_path?: string;
};

export function resolveFilePath(file: FileReference): string {
  return file.path || file.full_path || file.fullPath || file.file_path || file.filePath || '';
}

export function resolveFileName(file: FileReference, path: string): string {
  return file.name || path.split('/').filter(Boolean).pop() || path || 'File';
}

export function normalizeFileReference(file: FileReference): StructuredFile | null {
  const path = resolveFilePath(file);
  if (!path) return null;
  return {
    name: resolveFileName(file, path),
    path,
    operation: file.operation,
    sourcePath: file.sourcePath || file.source_path,
    kind: file.kind,
  };
}

function isUnavailableFileValue(value: string): boolean {
  return !value || value === '(not available)' || value.startsWith('(not ');
}

function stripFileLabelFormatting(value: string): string {
  return value
    .replace(/^[-*•]\s*/, '')
    .replace(/^\*\*([^*]+):\*\*\s*/, '$1: ')
    .replace(/^`([^`]+)`$/, '$1')
    .trim();
}

function extractLabelValue(line: string, label: 'File' | 'Path'): string | null {
  const normalized = stripFileLabelFormatting(line);
  const match = normalized.match(new RegExp(`^${label}:\\s*(.+)$`, 'i'));
  return match ? match[1].trim() : null;
}

function extractFirstAbsolutePath(value: string): string | null {
  const match = value.match(/(?:file:\/\/)?\/Users\/[^\s),]+(?:\s[^\s),]+)*/);
  if (!match) return null;
  return match[0].replace(/^file:\/\//, '').replace(/[.,;:]+$/, '');
}

function fileNameFromPath(path: string): string {
  return path.split('/').filter(Boolean).pop() || path || 'File';
}

function cleanFileName(value: string): string {
  const withoutSize = value.replace(/\s*\([^)]*\)\s*$/, '').trim();
  return withoutSize.replace(/^`|`$/g, '').trim();
}

export function extractFilesFromResult(resultText: string): ExtractedFile[] | null {
  if (!resultText) return null;

  const lines = resultText.split('\n');
  const files: ExtractedFile[] = [];
  const seenPaths = new Set<string>();
  let currentFileName: string | null = null;
  let currentFilePath: string | null = null;

  const addFile = (name: string, path: string) => {
    if (!path || seenPaths.has(path)) return;
    files.push({ name: name || fileNameFromPath(path), path });
    seenPaths.add(path);
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const fileValue = extractLabelValue(trimmed, 'File');
    const pathValue = extractLabelValue(trimmed, 'Path');

    if (fileValue !== null) {
      if (!isUnavailableFileValue(fileValue)) {
        const inlinePath = extractFirstAbsolutePath(fileValue);
        if (inlinePath) {
          addFile(fileNameFromPath(inlinePath), inlinePath);
          currentFileName = null;
          currentFilePath = null;
        } else {
          currentFileName = cleanFileName(fileValue);
        }
      }
    } else if (pathValue !== null) {
      if (!isUnavailableFileValue(pathValue)) {
        const extractedPath = extractFirstAbsolutePath(pathValue) || pathValue;
        currentFilePath = extractedPath;
      }
    }

    if (currentFileName && currentFilePath) {
      addFile(currentFileName, currentFilePath);
      currentFileName = null;
      currentFilePath = null;
    }
  }

  if (currentFileName && !currentFilePath) {
    addFile(currentFileName, `/Users/${currentFileName}`);
  }

  return files.length > 0 ? files : null;
}

export function formatBulletPoints(text: string): string {
  let result = text;
  result = result.replace(/ • /g, '\n\n• ');
  result = result.replace(/\n• /g, '\n\n• ');
  result = result.replace(/\n\n\n/g, '\n\n');
  result = result.replace(/^\n+/, '');
  return result;
}

export function isUserFacingResponseStreaming(isStreaming: boolean, result: string | undefined): boolean {
  return isStreaming && Boolean(result);
}
