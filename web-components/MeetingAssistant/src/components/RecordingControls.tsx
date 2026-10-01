import { memo, useEffect, useRef, useState } from 'react';
import type { MeetingUIStateDTO } from '../bridge/types';
import {
  cancelRecording,
  pauseRecording,
  resumeMeeting,
  resumeRecording,
  setLiveTranscription,
  startNewMeeting,
  toggleRecording,
} from '../bridge/meetingBridge';
import { useMeetingMeter } from '../bridge/meetingMeterStore';

interface RecordingControlsProps {
  ui: MeetingUIStateDTO;
}

function RecordingControls({ ui }: RecordingControlsProps) {
  const loadingModels = ui.transcriptionState === 'loadingModels';
  const [isConfirmingCancel, setIsConfirmingCancel] = useState(false);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const keepRecordingButtonRef = useRef<HTMLButtonElement>(null);
  const restoreCancelFocusRef = useRef(false);

  useEffect(() => {
    if (!ui.isRecording) setIsConfirmingCancel(false);
  }, [ui.isRecording]);

  useEffect(() => {
    if (!isConfirmingCancel) {
      // The Cancel button is disabled while confirming, so focus can only return after this render enables it.
      if (restoreCancelFocusRef.current) cancelButtonRef.current?.focus();
      restoreCancelFocusRef.current = false;
      return undefined;
    }
    keepRecordingButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      restoreCancelFocusRef.current = true;
      setIsConfirmingCancel(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isConfirmingCancel]);

  const confirmCancel = () => {
    setIsConfirmingCancel(false);
    cancelRecording();
  };

  return (
    <section className={`meeting-recording-controls${ui.isRecording ? ' is-recording' : ''}${ui.isCapturePaused ? ' is-paused' : ''}`}>
      {!ui.isRecording && !ui.isViewingPastMeeting && <StatusRow ui={ui} />}
      {ui.isViewingPastMeeting ? (
        <div className="meeting-recording-button-row">
          <button type="button" className="meeting-resume-button" onClick={resumeMeeting} disabled={loadingModels}>
            <PlayCircleIcon />
            Resume Meeting
          </button>
          <button type="button" className="meeting-start-new-button" onClick={startNewMeeting}>
            <PlusCircleIcon />
            Start New Meeting
          </button>
          <LiveTranscriptionSwitch enabled={ui.isLiveTranscriptionEnabled} />
        </div>
      ) : ui.isRecording ? (
        <>
          <div className="meeting-active-recording-row">
            <div className="meeting-recording-actions">
              <button type="button" className="meeting-record-button meeting-record-button--stop" onClick={toggleRecording} disabled={loadingModels}>
                <StopCircleIcon />
                End Meeting
              </button>
              {ui.isCapturePaused ? (
                <button type="button" className="meeting-record-button" onClick={resumeRecording}>
                  <PlayCircleIcon />
                  Resume
                </button>
              ) : (
                <button type="button" className="meeting-record-button" onClick={pauseRecording} disabled={ui.connectionState !== 'recording'}>
                  <PauseCircleIcon />
                  Pause
                </button>
              )}
              <button
                ref={cancelButtonRef}
                type="button"
                className="meeting-record-button meeting-record-button--cancel"
                onClick={() => setIsConfirmingCancel(true)}
                disabled={isConfirmingCancel}
              >
                <CancelCircleIcon />
                Cancel
              </button>
            </div>
            <StatusRow ui={ui} />
            <RecordingIndicators ui={ui} />
          </div>
          <LiveTranscriptionSwitch enabled={ui.isLiveTranscriptionEnabled} />
          {isConfirmingCancel && (
            <div className="meeting-cancel-confirmation" role="alertdialog" aria-labelledby="meeting-cancel-confirmation-message">
              <p id="meeting-cancel-confirmation-message">Discard this recording? The audio and transcript captured since you pressed Start Meeting or Resume Meeting will be deleted.</p>
              <div className="meeting-cancel-confirmation-actions">
                <button type="button" className="meeting-record-button meeting-record-button--stop" onClick={confirmCancel}>
                  Discard Recording
                </button>
                <button ref={keepRecordingButtonRef} type="button" className="meeting-record-button" onClick={() => setIsConfirmingCancel(false)}>
                  Keep Recording
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="meeting-recording-button-row">
          <button type="button" className="meeting-record-button" onClick={toggleRecording} disabled={loadingModels}>
            <RecordCircleIcon />
            Start Meeting
          </button>
          <LiveTranscriptionSwitch enabled={ui.isLiveTranscriptionEnabled} />
        </div>
      )}
    </section>
  );
}

function LiveTranscriptionSwitch({ enabled }: { enabled: boolean }) {
  return (
    <label className="meeting-switch-control meeting-live-transcription-switch">
      <span>Live transcription</span>
      <input type="checkbox" checked={enabled} onChange={(event) => setLiveTranscription(event.target.checked)} />
      <span className="meeting-switch-track" aria-hidden="true" />
    </label>
  );
}

function StatusRow({ ui }: { ui: MeetingUIStateDTO }) {
  return (
    <div className="meeting-status-row">
      <span className={`meeting-connection-indicator meeting-connection-indicator--${ui.connectionState}`} aria-hidden="true" />
      <span className="meeting-status-message">{ui.statusMessage}</span>
      {ui.transcriptionState !== 'idle' && <span className="meeting-transcription-state">{formatTranscriptionState(ui.transcriptionState)}</span>}
    </div>
  );
}

const RecordingIndicators = memo(function RecordingIndicators({ ui }: RecordingControlsProps) {
  const { microphoneAudioLevel, systemAudioLevel } = useMeetingMeter();
  return (
    <div className="meeting-recording-indicators">
      <span className="meeting-recording-time"><ClockIcon />{ui.recordingTimeString}</span>
      {ui.enableMicrophone && <SourceMeter label="Microphone" icon={<MicrophoneIcon />} level={microphoneAudioLevel} />}
      {ui.systemAudioCaptureMode !== 'none' && <SourceMeter label="System Audio" icon={<SpeakerIcon />} level={systemAudioLevel} />}
    </div>
  );
});

export default memo(RecordingControls);

function SourceMeter({ label, icon, level }: { label: string; icon: JSX.Element; level: number }) {
  const displayLevel = useSmoothedMeter(level);
  return (
    <span className="meeting-recording-source-meter">
      {icon}
      <span>{label}</span>
      <span className="meeting-audio-meter" role="meter" aria-label={`${label} level`} aria-valuenow={level} aria-valuemin={0} aria-valuemax={1}>
        <span className="meeting-audio-meter-fill" style={{ transform: `scaleX(${displayLevel})` }} />
      </span>
    </span>
  );
}

function useSmoothedMeter(level: number): number {
  const targetRef = useRef(clampMeterLevel(level));
  const displayedRef = useRef(clampMeterLevel(level));
  const [displayedLevel, setDisplayedLevel] = useState(displayedRef.current);

  useEffect(() => {
    targetRef.current = clampMeterLevel(level);
  }, [level]);

  useEffect(() => {
    let frameId = 0;
    let previousTimestamp = performance.now();

    const animate = (timestamp: number) => {
      const elapsedMs = Math.min(100, Math.max(0, timestamp - previousTimestamp));
      previousTimestamp = timestamp;
      const target = targetRef.current;
      const timeConstantMs = target > displayedRef.current ? 60 : 190;
      const blend = 1 - Math.exp(-elapsedMs / timeConstantMs);
      const next = displayedRef.current + ((target - displayedRef.current) * blend);
      displayedRef.current = Math.abs(target - next) < 0.001 ? target : next;
      setDisplayedLevel(displayedRef.current);
      frameId = requestAnimationFrame(animate);
    };

    frameId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameId);
  }, []);

  return displayedLevel;
}

function clampMeterLevel(level: number): number {
  return Math.min(1, Math.max(0, level));
}

function formatTranscriptionState(state: MeetingUIStateDTO['transcriptionState']) {
  switch (state) {
    case 'loadingModels': return 'Loading models';
    case 'listening': return 'Listening';
    case 'transcribing': return 'Transcribing';
    default: return '';
  }
}

function RecordCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><circle cx="8" cy="8" r="2.4" fill="currentColor" stroke="none" /></svg>;
}

function StopCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><rect x="5.5" y="5.5" width="5" height="5" rx=".5" fill="currentColor" stroke="none" /></svg>;
}

function PlayCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="m6.5 5.3 4.3 2.7-4.3 2.7V5.3Z" fill="currentColor" stroke="none" /></svg>;
}

function PlusCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M8 5v6M5 8h6" strokeLinecap="round" /></svg>;
}

function PauseCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="M6.6 5.6v4.8M9.4 5.6v4.8" strokeLinecap="round" /></svg>;
}

function CancelCircleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><circle cx="8" cy="8" r="5.7" /><path d="m5.9 5.9 4.2 4.2m0-4.2-4.2 4.2" strokeLinecap="round" /></svg>;
}

function ClockIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><circle cx="8" cy="8" r="5.5" /><path d="M8 4.7v3.6l2.4 1.4" strokeLinecap="round" /></svg>;
}

function MicrophoneIcon() {
  return <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="5.5" y="1.5" width="5" height="8" rx="2.5" /><path d="M3.7 7.4a4.3 4.3 0 0 0 8.6 0h1.2a5.5 5.5 0 0 1-4.9 5.45V15H7.4v-2.15A5.5 5.5 0 0 1 2.5 7.4h1.2Z" /></svg>;
}

function SpeakerIcon() {
  return <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M2 6h3l3-2.8v9.6L5 10H2V6Zm8.1-.8a4 4 0 0 1 0 5.6l-.8-.8a2.9 2.9 0 0 0 0-4l.8-.8Z" /></svg>;
}
