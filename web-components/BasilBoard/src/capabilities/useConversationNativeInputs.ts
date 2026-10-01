import { useCallback, useEffect, useRef } from 'react';
import type { ConversationVoiceCaptureState } from '../contracts';
import {
  cancelConversationVoiceCapture,
  registerConversationAttachmentErrorHandler,
  registerConversationFilesPickedHandler,
  registerConversationVoiceCaptureFinishedHandler,
  registerConversationVoiceCaptureStateHandler,
  saveConversationPastedImages,
} from '../services/bridge';

const MAX_PASTED_IMAGES = 10;

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') resolve(reader.result);
      else reject(new Error(`Could not read ${file.name || 'pasted image'}.`));
    };
    reader.onerror = () => reject(reader.error ?? new Error(`Could not read ${file.name || 'pasted image'}.`));
    reader.readAsDataURL(file);
  });
}

interface UseConversationNativeInputsOptions {
  focusEditor: () => void;
  onVoiceTranscription: (transcription: string) => void;
  onAttachmentPaths: (paths: string[]) => void;
  onAttachmentError: (message: string) => void;
  onVoiceStateChange: (state: ConversationVoiceCaptureState) => void;
  onVoiceError: (message?: string) => void;
}

export function useConversationNativeInputs({
  focusEditor,
  onVoiceTranscription,
  onAttachmentPaths,
  onAttachmentError,
  onVoiceStateChange,
  onVoiceError,
}: UseConversationNativeInputsOptions) {
  const voiceStateRef = useRef<ConversationVoiceCaptureState>('idle');

  const handlePastedImages = useCallback(async (files: File[]) => {
    const imageFiles = files.filter((file) => file.type.startsWith('image/'));
    if (imageFiles.length === 0) return;

    if (imageFiles.length > MAX_PASTED_IMAGES) {
      onAttachmentError(`You can paste up to ${MAX_PASTED_IMAGES} images at once.`);
      return;
    }

    try {
      const dataUrls = await Promise.all(imageFiles.map((file) => readFileAsDataUrl(file)));
      saveConversationPastedImages(dataUrls);
    } catch (error) {
      onAttachmentError(error instanceof Error ? error.message : 'Could not read pasted image.');
    }
  }, [onAttachmentError]);

  useEffect(
    () => registerConversationFilesPickedHandler((paths) => {
      onAttachmentPaths(paths);
      focusEditor();
    }),
    [focusEditor, onAttachmentPaths],
  );

  useEffect(
    () => registerConversationVoiceCaptureStateHandler((payload) => {
      voiceStateRef.current = payload.state;
      onVoiceStateChange(payload.state);
      if (payload.state === 'error' && payload.error) {
        onVoiceError(payload.error);
      } else if (payload.state !== 'error') {
        onVoiceError(undefined);
      }
    }),
    [onVoiceError, onVoiceStateChange],
  );

  useEffect(
    () => registerConversationVoiceCaptureFinishedHandler((payload) => {
      if (payload.error === 'canceled') {
        onVoiceError(undefined);
        onVoiceStateChange('idle');
        voiceStateRef.current = 'idle';
        return;
      }
      if (payload.error) {
        onVoiceError(payload.error);
        onVoiceStateChange('error');
        voiceStateRef.current = 'error';
        return;
      }
      const transcription = payload.transcription?.trim() ?? '';
      if (!transcription) {
        onVoiceError('no_speech');
        onVoiceStateChange('error');
        voiceStateRef.current = 'error';
        return;
      }
      onVoiceTranscription(transcription);
      onVoiceStateChange('idle');
      voiceStateRef.current = 'idle';
    }),
    [onVoiceError, onVoiceStateChange, onVoiceTranscription],
  );

  useEffect(
    () => registerConversationAttachmentErrorHandler((message) => {
      onAttachmentError(message);
    }),
    [onAttachmentError],
  );

  useEffect(() => () => {
    if (voiceStateRef.current === 'starting' || voiceStateRef.current === 'recording') {
      cancelConversationVoiceCapture();
    }
  }, []);

  return { handlePastedImages };
}

export { readFileAsDataUrl };
