// web-components/TranscriptionWidget/src/components/TranscriptionAudioBubble.tsx
//
// Isolates the animated bubble from meter-driven re-renders: it is the only leaf that reads useTranscriptionMeter(), so a 10Hz audio level tick can never force FullWidget/MinimizedWidget (buttons, model picker, timer) to re-render.

import AnimatedBubble from '../../../shared/bubble/AnimatedBubble';
import { useTranscriptionMeter } from '../bridge/transcriptionMeterStore';
import type { TranscriptionState } from '../state/transcriptionReducer';

interface TranscriptionAudioBubbleProps {
  size: number;
  bubbleMode: TranscriptionState['bubbleMode'];
  bubbleColors: TranscriptionState['bubbleColors'];
}

export function TranscriptionAudioBubble({ size, bubbleMode, bubbleColors }: TranscriptionAudioBubbleProps) {
  const audioLevel = useTranscriptionMeter();
  return (
    <AnimatedBubble
      size={size}
      mode={bubbleMode}
      baseColor={bubbleColors.base}
      accentColor={bubbleColors.accent}
      audioLevel={audioLevel}
    />
  );
}
