import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AudioFileUploadApp } from './AudioFileUploadApp';
import type { AudioFileUploadBridgeEvent } from '../bridge/audioFileUploadTypes';

let eventListener: ((event: AudioFileUploadBridgeEvent) => void) | null = null;
const mocks = vi.hoisted(() => ({
  selectAudioFile: vi.fn(),
  uploadAudioFile: vi.fn(),
  cancelAudioUpload: vi.fn(),
  dismissAudioUploadError: vi.fn(),
  minimizeAudioUpload: vi.fn(),
  collapseAudioUpload: vi.fn(),
  expandAudioUpload: vi.fn(),
}));

vi.mock('../bridge/audioFileUploadBridge', () => ({
  onAudioFileUploadEvent: (listener: (event: AudioFileUploadBridgeEvent) => void) => {
    eventListener = listener;
    return () => {
      eventListener = null;
    };
  },
  reportAudioUploadReady: vi.fn(),
  selectAudioFile: mocks.selectAudioFile,
  clearSelectedFile: vi.fn(),
  setDescription: vi.fn(),
  setLanguage: vi.fn(),
  uploadAudioFile: mocks.uploadAudioFile,
  copyTranscriptionResult: vi.fn(),
  cancelAudioUpload: mocks.cancelAudioUpload,
  dismissAudioUploadError: mocks.dismissAudioUploadError,
  minimizeAudioUpload: mocks.minimizeAudioUpload,
  collapseAudioUpload: mocks.collapseAudioUpload,
  expandAudioUpload: mocks.expandAudioUpload,
}));

beforeEach(() => {
  eventListener = null;
  mocks.selectAudioFile.mockClear();
  mocks.uploadAudioFile.mockClear();
  mocks.cancelAudioUpload.mockClear();
  mocks.dismissAudioUploadError.mockClear();
  mocks.minimizeAudioUpload.mockClear();
  mocks.collapseAudioUpload.mockClear();
  mocks.expandAudioUpload.mockClear();
});

describe('AudioFileUploadApp', () => {
  it('disables Upload and Transcribe until a file is selected', () => {
    render(<AudioFileUploadApp />);
    expect(screen.getByRole('button', { name: /upload and transcribe/i })).toBeDisabled();
  });

  it('enables Upload and Transcribe once canUpload is true', () => {
    render(<AudioFileUploadApp />);
    act(() => {
      eventListener?.({
        type: 'snapshot',
        revision: 1,
        protocolVersion: 1,
        hasSelectedFile: true,
        selectedFileName: 'clip.mp3',
        fileSizeDisplay: '2.1 MB',
        fileDurationDisplay: '0:42',
        description: '',
        selectedLanguage: 'auto',
        isUploading: false,
        uploadStatus: 'Preparing upload...',
        transcriptionResult: null,
        canUpload: true,
        errorMessage: null,
      });
    });
    expect(screen.getByRole('button', { name: /upload and transcribe/i })).toBeEnabled();
    expect(screen.getByText('clip.mp3')).toBeInTheDocument();
  });

  it('shows the upload progress state', () => {
    render(<AudioFileUploadApp />);
    act(() => {
      eventListener?.({
        type: 'snapshot',
        revision: 1,
        protocolVersion: 1,
        hasSelectedFile: true,
        selectedFileName: 'clip.mp3',
        fileSizeDisplay: null,
        fileDurationDisplay: null,
        description: '',
        selectedLanguage: 'auto',
        isUploading: true,
        uploadStatus: 'Uploading audio file...',
        transcriptionResult: null,
        canUpload: true,
        errorMessage: null,
      });
    });
    expect(screen.getByText('Uploading audio file...')).toBeInTheDocument();
  });

  it('shows the error banner when errorMessage is set', () => {
    render(<AudioFileUploadApp />);
    act(() => {
      eventListener?.({
        type: 'delta',
        revision: 1,
        protocolVersion: 1,
        errorMessage: 'Failed to upload file: Connection failed: timeout',
      });
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to upload file');
  });

  it('posts dismissError when the error banner is dismissed', async () => {
    render(<AudioFileUploadApp />);
    act(() => {
      eventListener?.({
        type: 'delta',
        revision: 1,
        protocolVersion: 1,
        errorMessage: 'Failed to upload file',
      });
    });

    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(mocks.dismissAudioUploadError).toHaveBeenCalledOnce();
  });

  it('posts selectAudioFile when the empty file zone is clicked', async () => {
    render(<AudioFileUploadApp />);
    await userEvent.click(screen.getByText(/click to select an audio file/i));
    expect(mocks.selectAudioFile).toHaveBeenCalledOnce();
  });

  it('posts cancelAudioUpload when Cancel is clicked', async () => {
    render(<AudioFileUploadApp />);
    await userEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
    expect(mocks.cancelAudioUpload).toHaveBeenCalledOnce();
  });

  it('renders the shared BasilWindowChrome controls and wires them to the bridge', async () => {
    render(<AudioFileUploadApp />);
    expect(screen.getByText('Upload Audio File')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /close window/i }));
    expect(mocks.cancelAudioUpload).toHaveBeenCalledOnce();

    await userEvent.click(screen.getByRole('button', { name: /minimize window/i }));
    expect(mocks.minimizeAudioUpload).toHaveBeenCalledOnce();

    await userEvent.click(screen.getByRole('button', { name: /collapse window/i }));
    expect(mocks.collapseAudioUpload).toHaveBeenCalledOnce();
  });
});
