import { companionPort, companionTargetIsRecording, companionTargetMeetingId, type CompanionTargetUi } from './companionTarget';
import { useCompanion } from './useCompanion';

/** Binds the Companion controller to whichever meeting the bridge snapshot says is current, for the embedded pane and the detached window alike. */
export function useMeetingCompanion(ui: CompanionTargetUi | null) {
  const meetingId = companionTargetMeetingId(ui);
  const isRecording = companionTargetIsRecording(ui);
  const companion = useCompanion({
    meetingId,
    port: companionPort(ui),
    selectedModelId: ui?.selectedAnalysisModelId ?? null,
    isRecording,
  });
  return { companion, meetingId, isRecording };
}
