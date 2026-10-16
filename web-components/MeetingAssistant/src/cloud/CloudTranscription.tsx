import { chipLabel, chipTone, fallbackNotice } from './cloudTranscriptionPresentation';
import type { CloudTranscriptionState } from './cloudTranscriptionTypes';

export interface CloudTranscriptionProps {
  state: CloudTranscriptionState | null;
}

/** A read-only status chip shown only while live transcription is connecting to, streaming from, or has failed over from the cloud service. Setup lives in Settings. */
export default function CloudTranscription({ state }: CloudTranscriptionProps) {
  if (state === null) return null;
  const tone = chipTone(state);
  if (tone !== 'connecting' && tone !== 'streaming' && tone !== 'fallback') return null;

  return (
    <div className="meeting-cloud">
      <span className={`meeting-cloud-chip meeting-cloud-chip--${tone}`} role="status" title={fallbackNotice(state.status) ?? undefined}>
        <span className="meeting-cloud-dot" aria-hidden="true" />
        <span className="meeting-cloud-chip-label">{chipLabel(state)}</span>
      </span>
    </div>
  );
}
