import type { MeetingUIStateDTO } from '../bridge/types';

export type CompanionTargetUi = Pick<
  MeetingUIStateDTO,
  'isRecording' | 'isViewingPastMeeting' | 'displayedMeetingWorkOwnerId' | 'selectedAnalysisModelId'
> & { recordingMeetingId?: string | null; companionApiPort?: number };

/** The meeting the Companion pane is about: the live one while recording, otherwise whatever the Notetaker is displaying. */
export function companionTargetMeetingId(ui: CompanionTargetUi | null): string | null {
  if (!ui) return null;
  if (ui.isRecording && !ui.isViewingPastMeeting && ui.recordingMeetingId) return ui.recordingMeetingId;
  return ui.displayedMeetingWorkOwnerId ?? null;
}

/** True when the target is the meeting being recorded, so live actions (Enable, Disable, chat, watches, sources) are meaningful. */
export function companionTargetIsRecording(ui: CompanionTargetUi | null): boolean {
  return Boolean(ui && ui.isRecording && !ui.isViewingPastMeeting && ui.recordingMeetingId);
}

export function companionPort(ui: CompanionTargetUi | null): number {
  const port = ui?.companionApiPort;
  return typeof port === 'number' && Number.isInteger(port) && port > 0 && port <= 65535 ? port : 0;
}
