import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SCOPE = 'html[data-surface-finish="metal_backdrop"]';

describe('Transcription windows surface finish', () => {
  const widgetEntry = readFileSync('src/entries/transcription-widget.tsx', 'utf8');
  const uploadEntry = readFileSync('src/entries/audio-file-upload.tsx', 'utf8');
  const uploadFinishCss = readFileSync('src/styles/audio-file-upload-surface-finish.css', 'utf8');
  const uploadCss = readFileSync('src/styles/audio-file-upload.css', 'utf8');

  it('opts the transcription widget in without its own finish stylesheet', () => {
    expect(widgetEntry).toContain('enableBackdropSurfaceFinish();');
    expect(widgetEntry).not.toContain('surface-finish.css');
  });

  it('opts the audio upload window in with its finish stylesheet', () => {
    expect(uploadEntry).toContain("import '../styles/audio-file-upload-surface-finish.css';");
    expect(uploadEntry).toContain('enableBackdropSurfaceFinish();');
  });

  it('clears the upload chrome while the transcription result stays solid', () => {
    expect(uploadFinishCss).toContain(`${SCOPE} :is(`);
    for (const chrome of ['.basil-window-header', '.basil-window-content', '.audio-upload-root']) {
      expect(uploadFinishCss).toContain(chrome);
    }
    expect(uploadFinishCss).toContain(`${SCOPE} .audio-upload-result {\n  background: var(--background-primary);\n}`);
    expect(uploadFinishCss.split(SCOPE).length - 1).toBe((uploadFinishCss.match(/\{/g) ?? []).length);
  });

  it('gives upload text fields a solid themed fill instead of the WebKit default', () => {
    const fieldRule = uploadCss.slice(uploadCss.indexOf('.audio-upload-form__field textarea,'));
    const fieldBlock = fieldRule.slice(0, fieldRule.indexOf('}'));
    expect(fieldBlock).toContain('color: var(--text-primary);');
    expect(fieldBlock).toContain('background: var(--background-primary);');
  });
});
