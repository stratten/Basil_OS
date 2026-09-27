import type { CaptureStateMessage } from '../types';
import { stopFollowUpCapture, cancelFollowUpCapture, stopNewAgentTaskCapture, cancelNewAgentTaskCapture, stopRefinementRecording } from '../services/bridge';
import AnimatedBubble from '../../../shared/bubble/AnimatedBubble';
import { useCaptureMeter } from '../store/captureMeterStore';

interface Props {
  captureState: CaptureStateMessage;
}

export default function InlineCapture({ captureState }: Props) {
  const audioLevel = useCaptureMeter();
  if (!captureState.isCapturing) return null;

  const isFollowUp = captureState.type === 'followUp';
  const isNewAgentTask = captureState.type === 'newAgentTask';
  const isRefinement = captureState.type === 'refinement';

  const label = isFollowUp
    ? 'Listening for follow-up AgentTask...'
    : isNewAgentTask
      ? 'Recording new AgentTask...'
      : 'Recording refinement...';

  const handleDone = () => {
    if (isFollowUp) stopFollowUpCapture();
    else if (isNewAgentTask) stopNewAgentTaskCapture();
    else if (isRefinement) stopRefinementRecording();
  };

  const handleCancel = () => {
    if (isFollowUp) cancelFollowUpCapture();
    else if (isNewAgentTask) cancelNewAgentTaskCapture();
    else if (isRefinement) stopRefinementRecording();
  };

  return (
    <div className="inline-capture">
      <div className="inline-capture-header">
        <span className="inline-capture-mic">
          <AnimatedBubble
            size={16}
            mode="audioResponsive"
            baseColor="var(--recording-base, #8B0000)"
            accentColor="var(--recording-accent, #FF6347)"
            audioLevel={audioLevel}
          />
        </span>
        <span className="inline-capture-label">{label}</span>
        <button className="done-btn" onClick={handleDone}>
          Done
        </button>
        <button
          className="action-btn"
          onClick={handleCancel}
          style={{ marginLeft: 'var(--padding-xs)' }}
        >
          Cancel
        </button>
      </div>
      {captureState.wordsDetected && (
        <div className="inline-capture-words">
          {captureState.wordsDetected}
        </div>
      )}
    </div>
  );
}
