import { describe, expect, it, vi } from 'vitest';
import {
  applyAudioFileUploadEvent,
  initialAudioFileUploadState,
  resolveAudioUploadTheme,
} from './audioFileUploadReducer';

describe('audioFileUploadReducer', () => {
  it('applies a matching snapshot and ignores stale deltas', () => {
    const snapshot = applyAudioFileUploadEvent(initialAudioFileUploadState, {
      type: 'snapshot',
      protocolVersion: 1,
      revision: 3,
      hasSelectedFile: true,
      selectedFileName: 'meeting.m4a',
      fileSizeDisplay: '1.2 MB',
      fileDurationDisplay: '0:42',
      description: 'Weekly sync',
      selectedLanguage: 'en',
      isUploading: false,
      uploadStatus: 'Ready to upload',
      transcriptionResult: null,
      canUpload: true,
      errorMessage: null,
    });

    const stale = applyAudioFileUploadEvent(snapshot, {
      type: 'delta',
      protocolVersion: 1,
      revision: 3,
      uploadStatus: 'Uploading audio file...',
    });

    expect(snapshot).toMatchObject({
      hasSnapshot: true,
      revision: 3,
      selectedFileName: 'meeting.m4a',
      canUpload: true,
    });
    expect(stale).toBe(snapshot);
  });

  it('rejects an incompatible protocol without changing state', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const result = applyAudioFileUploadEvent(initialAudioFileUploadState, {
      type: 'snapshot',
      protocolVersion: 2,
      revision: 1,
      hasSelectedFile: false,
      selectedFileName: null,
      fileSizeDisplay: null,
      fileDurationDisplay: null,
      description: '',
      selectedLanguage: 'auto',
      isUploading: false,
      uploadStatus: 'Ready',
      transcriptionResult: null,
      canUpload: false,
      errorMessage: null,
    });

    expect(result).toBe(initialAudioFileUploadState);
    expect(consoleError).toHaveBeenCalledOnce();
    consoleError.mockRestore();
  });

  it('uses its fallback theme until native initialization arrives', () => {
    expect(resolveAudioUploadTheme(initialAudioFileUploadState)).toMatchObject({
      primary: '#2F6FED',
      backgroundPrimary: '#FFFFFF',
    });
  });
});
