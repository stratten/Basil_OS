import type { AgentTaskArtifactReviewKind } from '../../artifacts/artifactContract';
import type { FilePreviewKind } from '../../services/bridge';

export type FilePreviewRenderMode =
  | 'loading'
  | 'markdown'
  | 'live_html'
  | 'source'
  | 'native_pdf'
  | 'image'
  | 'unsupported';

export interface FilePreviewPresentation {
  label: string;
  renderMode: FilePreviewRenderMode;
}

export function filePreviewNameFromPath(path: string): string {
  return path.split('/').filter(Boolean).pop() || path || 'File Preview';
}

/**
 * The preview kind a document review kind corresponds to, so a window that knows the file from its task can still label it when the native layer does not recognize the extension.
 */
export function filePreviewKindForReviewKind(kind: AgentTaskArtifactReviewKind | undefined): FilePreviewKind | undefined {
  switch (kind) {
    case 'markdown':
      return 'markdown';
    case 'html':
      return 'htmlSource';
    case 'text':
      return 'text';
    case 'code':
    case 'json':
    case 'yaml':
    case 'xml':
      return 'code';
    case 'pdf':
      return 'pdf';
    default:
      return undefined;
  }
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
    case 'image':
      return { label: 'Image Preview', renderMode: 'image' };
    case 'unsupported':
      return { label: 'File Preview', renderMode: 'unsupported' };
    default:
      return { label: 'Loading Preview', renderMode: 'loading' };
  }
}
