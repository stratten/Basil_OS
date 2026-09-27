import { describe, expect, it } from 'vitest';
import type { FilePreviewKind } from '../../services/bridge';
import {
  filePreviewNameFromPath,
  presentFilePreview,
  type FilePreviewRenderMode,
} from './filePreviewPresentation';

const knownKinds: Array<[FilePreviewKind, string, FilePreviewRenderMode]> = [
  ['markdown', 'Markdown Preview', 'markdown'],
  ['htmlSource', 'HTML Preview', 'live_html'],
  ['code', 'Code Preview', 'source'],
  ['text', 'Text Preview', 'source'],
  ['pdf', 'PDF Preview', 'native_pdf'],
  ['unsupported', 'File Preview', 'unsupported'],
];

describe('file preview presentation policy', () => {
  it.each(knownKinds)('maps %s to its existing label and render mode', (kind, label, renderMode) => {
    expect(presentFilePreview(kind)).toEqual({ label, renderMode });
  });

  it('keeps the existing loading fallback for an absent payload kind', () => {
    expect(presentFilePreview(undefined)).toEqual({
      label: 'Loading Preview',
      renderMode: 'loading',
    });
  });

  it('preserves path-derived names for Unicode, trailing-slash, and empty paths', () => {
    expect(filePreviewNameFromPath('/private/reports/résumé-東京.md')).toBe('résumé-東京.md');
    expect(filePreviewNameFromPath('/private/reports/')).toBe('reports');
    expect(filePreviewNameFromPath('')).toBe('File Preview');
  });
});
