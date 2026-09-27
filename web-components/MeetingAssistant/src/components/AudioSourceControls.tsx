import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import type { MeetingUIStateDTO } from '../bridge/types';
import { setAudioSource } from '../bridge/meetingBridge';

interface AudioSourceControlsProps {
  ui: MeetingUIStateDTO;
}

export default function AudioSourceControls({ ui }: AudioSourceControlsProps) {
  const disabled = ui.isRecording || ui.isViewingPastMeeting;
  const [isAudioSourceMenuOpen, setIsAudioSourceMenuOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  const selectedAudioSource = ui.systemAudioCaptureMode === 'selectedProcess'
    ? `process:${ui.selectedAudioProcessId ?? ''}`
    : ui.systemAudioCaptureMode;
  const selectedProcess = ui.availableAudioProcesses
    .flatMap((group) => group.processes)
    .find((process) => `process:${process.id}` === selectedAudioSource);

  useEffect(() => {
    if (!isAudioSourceMenuOpen) return;
    const dismissMenu = (event: PointerEvent) => {
      if (!pickerRef.current?.contains(event.target as Node)) {
        setIsAudioSourceMenuOpen(false);
      }
    };
    window.addEventListener('pointerdown', dismissMenu);
    return () => window.removeEventListener('pointerdown', dismissMenu);
  }, [isAudioSourceMenuOpen]);

  const handleAudioSourceChange = (value: string) => {
    setIsAudioSourceMenuOpen(false);
    if (value.startsWith('process:')) {
      setAudioSource({ captureMode: 'selectedProcess', processId: Number(value.slice('process:'.length)) });
      return;
    }
    setAudioSource({ captureMode: value as MeetingUIStateDTO['systemAudioCaptureMode'] });
  };

  return (
    <section className="meeting-audio-source-section">
      <label className="meeting-audio-toggle">
        <MicrophoneIcon />
        <span>Microphone</span>
        <input
          type="checkbox"
          checked={ui.enableMicrophone}
          disabled={disabled}
          onChange={(event) => setAudioSource({ enableMicrophone: event.target.checked })}
        />
        <span className="meeting-audio-switch" aria-hidden="true" />
      </label>

      {ui.isSystemAudioAvailable ? (
        <div className="meeting-system-audio-picker">
          <SystemAudioIcon />
          <span id={`${listboxId}-label`}>Audio Source</span>
          <div className="meeting-audio-source-picker" ref={pickerRef}>
            <button
              type="button"
              className="meeting-audio-mode-select"
              role="combobox"
              aria-controls={listboxId}
              aria-expanded={isAudioSourceMenuOpen}
              aria-haspopup="listbox"
              aria-labelledby={`${listboxId}-label`}
              id={`${listboxId}-value`}
              onClick={() => setIsAudioSourceMenuOpen((isOpen) => !isOpen)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') setIsAudioSourceMenuOpen(false);
                if (event.key === 'ArrowDown' && !isAudioSourceMenuOpen) {
                  event.preventDefault();
                  setIsAudioSourceMenuOpen(true);
                }
              }}
              disabled={disabled}
            >
              <AudioSourceOptionIcon process={selectedProcess} mode={ui.systemAudioCaptureMode} />
              <span className="meeting-audio-source-value">
                {selectedProcess?.name ?? (ui.systemAudioCaptureMode === 'none' ? 'None (Mic Only)' : 'System Audio (All Apps)')}
              </span>
              <ChevronIcon />
            </button>
            {isAudioSourceMenuOpen && (
              <div
                className="meeting-audio-source-menu"
                id={listboxId}
                role="listbox"
                aria-labelledby={`${listboxId}-label`}
                aria-activedescendant={`${listboxId}-${selectedAudioSource.replace(':', '-')}`}
              >
                <AudioSourceOption
                  id={`${listboxId}-globalOutput`}
                  isSelected={selectedAudioSource === 'globalOutput'}
                  label="System Audio (All Apps)"
                  onSelect={() => handleAudioSourceChange('globalOutput')}
                  icon={<SystemAudioIcon />}
                />
                <AudioSourceOption
                  id={`${listboxId}-none`}
                  isSelected={selectedAudioSource === 'none'}
                  label="None (Mic Only)"
                  onSelect={() => handleAudioSourceChange('none')}
                  icon={<MicrophoneIcon />}
                />
                {ui.availableAudioProcesses.map((group) => (
                  group.processes.length > 0 && (
                    <div key={group.id} className="meeting-audio-source-group" role="group" aria-label={group.title}>
                      <span className="meeting-audio-source-group-label">{group.title}</span>
                      {group.processes.map((process) => (
                        <AudioSourceOption
                          key={process.id}
                          id={`${listboxId}-process-${process.id}`}
                          isSelected={selectedAudioSource === `process:${process.id}`}
                          label={process.name}
                          onSelect={() => handleAudioSourceChange(`process:${process.id}`)}
                          icon={<AudioSourceOptionIcon process={process} />}
                          isAudioActive={process.audioActive}
                        />
                      ))}
                    </div>
                  )
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <p className="meeting-audio-unavailable">System audio capture is unavailable on this Mac.</p>
      )}

      {ui.microphoneInputRecoveryState !== 'idle' && (
        <p className="meeting-audio-recovery-notice" role="alert">
          {ui.microphoneInputRecoveryState === 'reconnecting'
            ? 'Reconnecting to the microphone…'
            : ui.microphoneInputRecoveryMessage ?? 'Microphone input failed.'}
        </p>
      )}
    </section>
  );
}

interface AudioSourceOptionProps {
  id: string;
  isSelected: boolean;
  label: string;
  onSelect: () => void;
  icon: ReactNode;
  isAudioActive?: boolean;
}

function AudioSourceOption({ id, isSelected, label, onSelect, icon, isAudioActive = false }: AudioSourceOptionProps) {
  return (
    <button
      type="button"
      className={`meeting-audio-source-option${isSelected ? ' is-selected' : ''}`}
      id={id}
      role="option"
      aria-selected={isSelected}
      onClick={onSelect}
    >
      {icon}
      <span>{label}</span>
      {isAudioActive && <SystemAudioIcon className="meeting-audio-active-icon" />}
      {isSelected && <CheckmarkIcon />}
    </button>
  );
}

function AudioSourceOptionIcon({ process, mode }: {
  process?: MeetingUIStateDTO['availableAudioProcesses'][number]['processes'][number];
  mode?: MeetingUIStateDTO['systemAudioCaptureMode'];
}) {
  if (process?.iconDataUrl) {
    return <img className="meeting-audio-process-icon" src={process.iconDataUrl} alt="" />;
  }
  if (process) return <ApplicationIcon />;
  return mode === 'none' ? <MicrophoneIcon /> : <SystemAudioIcon />;
}

function MicrophoneIcon() {
  return (
    <svg className="meeting-inline-icon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" />
      <path d="M3.7 7.4a4.3 4.3 0 0 0 8.6 0h1.2a5.5 5.5 0 0 1-4.9 5.45V15H7.4v-2.15A5.5 5.5 0 0 1 2.5 7.4h1.2Z" />
    </svg>
  );
}

function SystemAudioIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={`meeting-inline-icon ${className}`.trim()} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M2 6h3l3-2.8v9.6L5 10H2V6Zm8.1-.8a4 4 0 0 1 0 5.6l-.8-.8a2.9 2.9 0 0 0 0-4l.8-.8Zm1.9-2a6.7 6.7 0 0 1 0 9.6l-.8-.8a5.6 5.6 0 0 0 0-8l.8-.8Z" />
    </svg>
  );
}

function ApplicationIcon() {
  return (
    <svg className="meeting-inline-icon meeting-audio-process-fallback-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true">
      <rect x="2.2" y="2.2" width="11.6" height="11.6" rx="2.2" />
      <path d="M2.6 5.2h10.8M5.2 2.6v2.2" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg className="meeting-audio-source-chevron" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m3.5 4.75 2.5 2.5 2.5-2.5" />
    </svg>
  );
}

function CheckmarkIcon() {
  return (
    <svg className="meeting-audio-source-checkmark" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m2.5 6 2.1 2.1 4.9-4.9" />
    </svg>
  );
}
