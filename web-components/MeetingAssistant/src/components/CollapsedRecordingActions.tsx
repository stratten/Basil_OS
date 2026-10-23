import type { MeetingUIStateDTO } from '../bridge/types';
import { pauseRecording, resumeRecording, toggleRecording } from '../bridge/meetingBridge';
import { PauseCircleIcon, PlayCircleIcon, StopCircleIcon } from './MeetingIcons';

interface CollapsedRecordingActionsProps {
  ui: MeetingUIStateDTO;
}

/** Pause/Resume and End for the collapsed Notetaker header, mirroring the expanded controls' handlers and enablement. */
export default function CollapsedRecordingActions({ ui }: CollapsedRecordingActionsProps) {
  const loadingModels = ui.transcriptionState === 'loadingModels';
  return (
    <div className="meeting-collapsed-actions" role="group" aria-label="Recording controls">
      {ui.isCapturePaused ? (
        <button type="button" className="meeting-collapsed-action" onClick={resumeRecording} aria-label="Resume recording" title="Resume recording">
          <PlayCircleIcon />
        </button>
      ) : (
        <button
          type="button"
          className="meeting-collapsed-action"
          onClick={pauseRecording}
          disabled={ui.connectionState !== 'recording'}
          aria-label="Pause recording"
          title="Pause recording"
        >
          <PauseCircleIcon />
        </button>
      )}
      <button
        type="button"
        className="meeting-collapsed-action meeting-collapsed-action--stop"
        onClick={toggleRecording}
        disabled={loadingModels}
        aria-label="End recording"
        title="End recording"
      >
        <StopCircleIcon />
      </button>
    </div>
  );
}
