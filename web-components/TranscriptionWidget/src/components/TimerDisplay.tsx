// web-components/TranscriptionWidget/src/components/TimerDisplay.tsx

function formatSeconds(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(clamped / 60);
  const seconds = clamped % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

export function TimerDisplay({ seconds, compact = false }: { seconds: number; compact?: boolean }) {
  return (
    <span className={compact ? 'transcription-timer transcription-timer--compact' : 'transcription-timer'}>
      {formatSeconds(seconds)}
    </span>
  );
}
