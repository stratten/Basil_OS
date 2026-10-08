// web-components/TranscriptionWidget/src/components/TimerDisplay.tsx

import { formatClockSeconds } from '@shared/formatClockSeconds';

export function TimerDisplay({ seconds, compact = false }: { seconds: number; compact?: boolean }) {
  return (
    <span className={compact ? 'transcription-timer transcription-timer--compact' : 'transcription-timer'}>
      {formatClockSeconds(seconds)}
    </span>
  );
}
