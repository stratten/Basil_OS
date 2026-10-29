import type { CaptureInitMessage, CaptureSnapshot, FontConfig, ThemeConfig } from '../types';

let nextRevision = 1;
function revision(): number {
  return nextRevision++;
}

export function baseVoiceSnapshot(overrides: Partial<CaptureSnapshot> = {}): CaptureSnapshot {
  return {
    revision: revision(),
    inputModality: 'voice',
    isCapturing: false,
    hasCompleted: false,
    statusMessage: 'Listening...',
    wordsDetected: [],
    silenceDetectionActive: false,
    silenceRemaining: 0,
    useIntelligentCapture: true,
    progressPercentage: 1,
    remainingSeconds: 10,
    agentTaskHotkeyDisplay: '⌥P',
    textPrompt: '',
    isSubmittingTextPrompt: false,
    selectedModelId: null,
    referencePaths: [],
    isDraggingOver: false,
    ...overrides,
  };
}

export function baseTextSnapshot(overrides: Partial<CaptureSnapshot> = {}): CaptureSnapshot {
  return {
    ...baseVoiceSnapshot(),
    inputModality: 'text',
    statusMessage: '',
    ...overrides,
  };
}

export const voiceRecordingSnapshot: CaptureSnapshot = baseVoiceSnapshot({
  isCapturing: true,
  statusMessage: 'Listening...',
  wordsDetected: ['schedule', 'a', 'meeting'],
  progressPercentage: 0.6,
  remainingSeconds: 6,
});

export const voiceSilenceCountdownSnapshot: CaptureSnapshot = baseVoiceSnapshot({
  isCapturing: true,
  statusMessage: 'Listening...',
  wordsDetected: ['schedule', 'a', 'meeting'],
  silenceDetectionActive: true,
  silenceRemaining: 1.4,
  progressPercentage: 0.2,
  remainingSeconds: 2,
});

export const voiceProcessingSnapshot: CaptureSnapshot = baseVoiceSnapshot({
  isCapturing: false,
  statusMessage: 'Processing...',
  wordsDetected: ['schedule', 'a', 'meeting'],
  progressPercentage: 0,
  remainingSeconds: 0,
});

export const voiceCanceledSnapshot: CaptureSnapshot = baseVoiceSnapshot({
  isCapturing: false,
  statusMessage: 'Canceled',
});

export const textEmptyDraftSnapshot: CaptureSnapshot = baseTextSnapshot();

export const textWithDraftSnapshot: CaptureSnapshot = baseTextSnapshot({
  textPrompt: 'Draft a summary of yesterday\'s standup notes',
});

export const textSubmittingSnapshot: CaptureSnapshot = baseTextSnapshot({
  textPrompt: 'Draft a summary of yesterday\'s standup notes',
  isSubmittingTextPrompt: true,
});

export const withReferencePaths = (
  snapshot: CaptureSnapshot,
  entries: CaptureSnapshot['referencePaths']
): CaptureSnapshot => ({ ...snapshot, referencePaths: entries, revision: revision() });

export const sampleReferencePaths: CaptureSnapshot['referencePaths'] = [
  { path: '/Users/basil-user/Documents/Q3-report.pdf', isDirectory: false },
  { path: '/Users/basil-user/Documents/project-assets/', isDirectory: true },
];

export const draggingOverSnapshot: CaptureSnapshot = baseVoiceSnapshot({ isDraggingOver: true });

export const sampleTheme: ThemeConfig = {
  backgroundPrimary: '#FFFFFF',
  primary: '#33559B',
  secondary: '#003087',
  textPrimary: '#000000',
  recordingBase: '#8B0000',
  recordingAccent: '#FF6347',
  processingBase: '#7C3AED',
  processingAccent: '#DDD6FE',
  warningBase: '#FFA500',
};

export const sampleFonts: FontConfig = {
  fontFamily: 'Helvetica',
  fontFamilyMedium: 'Helvetica-Bold',
  fontFamilyBold: 'Helvetica-Bold',
};

export function buildInitMessage(snapshot: CaptureSnapshot, port = 51823): CaptureInitMessage {
  return {
    port,
    agentTaskDisplayName: 'Paprika',
    theme: sampleTheme,
    fonts: sampleFonts,
    snapshot,
  };
}
