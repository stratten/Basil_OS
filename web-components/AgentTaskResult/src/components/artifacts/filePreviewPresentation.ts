import type { FilePreviewKind } from '../../services/bridge';

export type FilePreviewRenderMode =
  | 'loading'
  | 'markdown'
  | 'live_html'
  | 'source'
  | 'native_pdf'
  | 'unsupported';

export interface FilePreviewPresentation {
  label: string;
  renderMode: FilePreviewRenderMode;
}

export function filePreviewNameFromPath(path: string): string {
  return path.split('/').filter(Boolean).pop() || path || 'File Preview';
}

export function presentFilePreview(kind: FilePreviewKind | undefined): FilePreviewPresentation {
  switch (kind) {
    case 'markdown':
      return { label: 'Markdown Preview', renderMode: 'markdown' };
    case 'htmlSource':
      return { label: 'HTML Preview', renderMode: 'live_html' };
    case 'code':
      return { label: 'Code Preview', renderMode: 'source' };
    case 'text':
      return { label: 'Text Preview', renderMode: 'source' };
    case 'pdf':
      return { label: 'PDF Preview', renderMode: 'native_pdf' };
    case 'unsupported':
      return { label: 'File Preview', renderMode: 'unsupported' };
    default:
      return { label: 'Loading Preview', renderMode: 'loading' };
  }
}
