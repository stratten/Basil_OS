// web-components/TranscriptionWidget/src/components/ErrorBadgePopover.tsx

import { showTranscriptionError } from '../bridge/transcriptionWidgetBridge';
import { TranscriptionSymbol } from './TranscriptionSymbol';

export function ErrorBadgePopover({ error }: { error: string | null }) {
  if (!error) return null;

  return (
    <div className="transcription-error-badge-wrapper">
      <button
        type="button"
        className="transcription-error-badge"
        aria-label="Transcription failed"
        title={error}
        onClick={() => showTranscriptionError()}
      >
        <TranscriptionSymbol name="warning" size={12} />
      </button>
    </div>
  );
}
