import type { CaptureSnapshot } from '../types';
import { deriveBubbleColors, deriveBubbleMode } from '../types';
import AnimatedBubble from '../../../shared/bubble/AnimatedBubble';
import CaptureProgressRing from './CaptureProgressRing';
import CaptureModelPickerMenu from './CaptureModelPickerMenu';
import { useCaptureAudioLevel } from './useCaptureAudioLevel';
import { pickReferenceFiles, showNativeModelPicker } from '../services/bridge';

interface Props {
  snapshot: CaptureSnapshot;
  selectedModelId: string | null;
  onModelChange: (modelId: string | null) => void;
}

const BUBBLE_SIZE = 50;
const RING_SIZE = 56;

export default function VoiceCaptureView({ snapshot, selectedModelId, onModelChange }: Props) {
  const audioLevel = useCaptureAudioLevel();
  const mode = deriveBubbleMode(snapshot);
  const { baseColor, accentColor } = deriveBubbleColors(snapshot);
  const words = snapshot.wordsDetected.length === 0
    ? 'Listening...'
    : snapshot.wordsDetected.slice(-3).join(' ');

  return (
    <div className="voice-capture-body">
      <div className="voice-capture-body__detected">
        <span className="voice-capture-body__detected-label">Detected:</span>
        <span className={`voice-capture-body__words${snapshot.wordsDetected.length === 0 ? ' voice-capture-body__words--idle' : ''}`}>{words}</span>
      </div>
      <div className="voice-capture-body__bubble-wrap" style={{ width: RING_SIZE, height: RING_SIZE }}>
        <AnimatedBubble
          size={BUBBLE_SIZE}
          mode={mode}
          baseColor={baseColor}
          accentColor={accentColor}
          audioLevel={audioLevel}
        />
        {snapshot.silenceDetectionActive ? (
          <CaptureProgressRing
            size={RING_SIZE}
            progress={snapshot.silenceRemaining / 2}
            color="orange"
            strokeWidth={3}
            gradientFrom="orange"
            gradientTo="red"
          />
        ) : !snapshot.useIntelligentCapture && snapshot.isCapturing ? (
          <>
            <CaptureProgressRing
              size={RING_SIZE}
              progress={snapshot.progressPercentage}
              color="var(--secondary)"
              gradientFrom="var(--secondary)"
              gradientTo="var(--primary)"
            />
            <span className="voice-capture-body__timer">{snapshot.remainingSeconds}</span>
          </>
        ) : null}
      </div>
      <div className="voice-capture-body__status-block">
        <span className="voice-capture-body__status">{snapshot.statusMessage}</span>
        {snapshot.isCapturing && snapshot.agentTaskHotkeyDisplay ? (
          <span className="voice-capture-body__hotkey">Press {snapshot.agentTaskHotkeyDisplay} when done</span>
        ) : null}
      </div>
      <div className="voice-capture-body__actions">
        <button
          type="button"
          className="voice-capture-body__attach"
          onClick={() => pickReferenceFiles()}
          title="Attach files or folders"
        >
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
          </svg>
          <span>Attach</span>
        </button>
        <div className="voice-capture-body__model-picker">
          <CaptureModelPickerMenu
            disabled={snapshot.hasCompleted}
            selectedModelId={selectedModelId}
            onModelChange={onModelChange}
            variant="miniChevron"
            onRequestNativeMenu={(models, currentModelId, anchorRect) => {
              showNativeModelPicker(
                models.map((model) => ({
                  id: model.id,
                  displayName: model.display_name,
                  category: model.category,
                })),
                currentModelId,
      {
        x: anchorRect.x,
        y: anchorRect.y,
        width: anchorRect.width,
        height: anchorRect.height,
      },
              );
            }}
          />
        </div>
      </div>
    </div>
  );
}
