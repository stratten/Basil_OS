import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import type { MeetingUIStateDTO } from '../bridge/types';
import { LOCAL_LIVE_MODEL_LABEL, liveEngineChoice, liveModelOptions, liveModelValue } from '../cloud/cloudTranscriptionPresentation';
import type { CloudTranscriptionState } from '../cloud/cloudTranscriptionTypes';

export interface LiveTranscriptionModelSelectProps {
  ui: MeetingUIStateDTO;
  state: CloudTranscriptionState | null;
  onChoose: (engine: string | null) => void;
}

/** Chooses the engine for the next recording only, with the same shared picker the other model selectors use. It starts on the default from Settings, has more than one choice only when the user already set up and acknowledged a cloud service there, and only appears while Live Transcribe is on. */
export default function LiveTranscriptionModelSelect({ ui, state, onChoose }: LiveTranscriptionModelSelectProps) {
  if (!ui.isLiveTranscriptionEnabled) return null;
  const options = liveModelOptions(state, LOCAL_LIVE_MODEL_LABEL);
  return (
    <label className="meeting-tools-model meeting-live-model">
      <span>Model:</span>
      <ReasoningModelPicker
        models={options.map((option) => ({ id: option.value, name: option.label, category: option.category }))}
        selectedModelId={liveModelValue(state, options, ui.liveEngineOverride)}
        disabled={false}
        ariaLabel="Live transcription model"
        onModelChange={(value) => {
          if (value !== undefined) onChoose(liveEngineChoice(value, state, options));
        }}
      />
    </label>
  );
}
