import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import ReasoningModelPicker, { type SharedReasoningModel } from '../../../shared/ReasoningModelPicker';
import { formatClockSeconds } from '@shared/formatClockSeconds';
import type { MeetingUIStateDTO } from '../bridge/types';
import { setAutomation, setPostProcessingModel, startPostProcessing } from '../bridge/meetingBridge';

const AUTOMATION_POPOVER_THEME_PROPERTIES = [
  '--background-primary',
  '--background-secondary',
  '--background-tertiary',
  '--text-primary',
  '--text-secondary',
  '--primary',
  '--secondary',
  '--field-border',
  '--separator-color',
  '--shadow-dark',
  '--font-family-light',
  '--font-family-medium',
  '--font-size-headline',
  '--font-size-body',
  '--font-size-status-small',
] as const;

export default function TranscriptToolsCard({ ui }: { ui: MeetingUIStateDTO }) {
  const [automationOpen, setAutomationOpen] = useState(false);
  const [automationPosition, setAutomationPosition] = useState({ left: 0, top: 0 });
  const [automationTheme, setAutomationTheme] = useState<Record<string, string>>({});
  const automationRef = useRef<HTMLDivElement | null>(null);
  const automationButtonRef = useRef<HTMLButtonElement | null>(null);
  const automationPopoverRef = useRef<HTMLDivElement | null>(null);
  const activeForSelection = ui.isPostProcessing
    && ui.activePostProcessingMeetingId === ui.displayedMeetingWorkOwnerId;
  const busyWithAnotherMeeting = ui.isPostProcessing && !activeForSelection;
  const postProcessingPercent = Math.round(ui.postProcessingAggregateProgress * 100);
  const transcriptionModels: SharedReasoningModel[] = ui.availableModels.map((model) => ({
    id: model.id,
    name: model.displayName,
    category: model.category,
  }));
  const selectedTranscriptionModelId = ui.availableModels.find(
    (model) => model.id === ui.postProcessingModel || model.displayName === ui.postProcessingModel,
  )?.id;
  const automationModes = [
    ['summary', 'Summary'],
    ['action_items', 'Action Items'],
    ['suggested_actions', 'To-Do Candidates'],
    ['decisions', 'Key Decisions'],
    ['questions', 'Questions & Answers'],
    ['sentiment', 'Sentiment'],
  ] as const;
  const toggleAutomationMode = (mode: string, enabled: boolean) => {
    const next = enabled
      ? Array.from(new Set([...ui.sessionAutoAnalyzeModes, mode]))
      : ui.sessionAutoAnalyzeModes.filter((candidate) => candidate !== mode);
    setAutomation({ autoAnalyzeModes: next });
  };

  function positionAutomationPopover(): void {
    const buttonBounds = automationButtonRef.current?.getBoundingClientRect();
    if (!buttonBounds) return;
    const viewportPadding = 8;
    const popoverWidth = 320;
    const measuredHeight = automationPopoverRef.current?.getBoundingClientRect().height ?? 0;
    const left = Math.max(
      viewportPadding,
      Math.min(buttonBounds.right - popoverWidth, window.innerWidth - popoverWidth - viewportPadding),
    );
    const opensDownward = window.innerHeight - buttonBounds.bottom >= measuredHeight + viewportPadding
      || buttonBounds.top < measuredHeight + viewportPadding;
    const top = opensDownward
      ? buttonBounds.bottom + 8
      : Math.max(viewportPadding, buttonBounds.top - measuredHeight - 8);
    setAutomationPosition({ left, top });
  }

  // Rendered through a portal (see below), so the popover can escape the
  // Transcript Tools card's bounds instead of being clipped by a scrolling
  // ancestor and forcing the user to scroll the underlying page to reach the
  // bottom of what is meant to be a small, transient control.
  useLayoutEffect(() => {
    if (automationOpen) positionAutomationPopover();
  }, [automationOpen, ui.sessionAutoAnalyzeOnComplete]);

  useEffect(() => {
    if (!automationOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!automationRef.current?.contains(target) && !automationPopoverRef.current?.contains(target)) {
        setAutomationOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setAutomationOpen(false);
        automationButtonRef.current?.focus();
      }
    };
    const handleReposition = () => positionAutomationPopover();
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('resize', handleReposition);
    window.addEventListener('scroll', handleReposition, true);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('resize', handleReposition);
      window.removeEventListener('scroll', handleReposition, true);
    };
  }, [automationOpen]);

  return (
    <section className="meeting-transcript-tools-card">
      <div className="meeting-tools-header">
        <h2>Transcript Tools</h2>
        <div className="meeting-automation-control" ref={automationRef}>
          <button
            ref={automationButtonRef}
            type="button"
            className="meeting-automation-button"
            aria-expanded={automationOpen}
            onClick={() => {
              if (!automationOpen) {
                const computedStyle = getComputedStyle(automationButtonRef.current ?? document.documentElement);
                setAutomationTheme(Object.fromEntries(
                  AUTOMATION_POPOVER_THEME_PROPERTIES.map((property) => [property, computedStyle.getPropertyValue(property)]),
                ));
              }
              setAutomationOpen((open) => !open);
            }}
          >
            <AutomationIcon />
            Automation
          </button>
          {automationOpen && createPortal(
            <div
              ref={automationPopoverRef}
              className="meeting-automation-popover"
              role="dialog"
              aria-label="Automation for this recording"
              style={{ position: 'fixed', left: automationPosition.left, top: automationPosition.top, ...automationTheme } as CSSProperties}
            >
              <h3>Automation (this recording)</h3>
              <p>Seeded from your saved defaults. Changes here apply only to the current recording.</p>
              <SwitchControl label="Auto-retranscribe on stop" checked={ui.sessionAutoRetranscribeOnStop} onChange={(checked) => setAutomation({ autoRetranscribeOnStop: checked })} />
              <SwitchControl label="Auto-analyze on complete" checked={ui.sessionAutoAnalyzeOnComplete} onChange={(checked) => setAutomation({ autoAnalyzeOnComplete: checked })} />
              {ui.sessionAutoAnalyzeOnComplete && (
                <div className="meeting-automation-analysis-options">
                  <fieldset>
                    <legend>Run analysis</legend>
                    <label><input type="radio" name="meeting-auto-analysis-timing" checked={ui.sessionAutoAnalyzeTiming === 'after'} onChange={() => setAutomation({ autoAnalyzeTiming: 'after' })} />After re-transcription</label>
                    <label><input type="radio" name="meeting-auto-analysis-timing" checked={ui.sessionAutoAnalyzeTiming === 'before'} onChange={() => setAutomation({ autoAnalyzeTiming: 'before' })} />Before re-transcription</label>
                  </fieldset>
                  <fieldset>
                    <legend>Modes</legend>
                    {automationModes.map(([mode, label]) => (
                      <SwitchControl key={mode} label={label} checked={ui.sessionAutoAnalyzeModes.includes(mode)} onChange={(checked) => toggleAutomationMode(mode, checked)} />
                    ))}
                  </fieldset>
                  <label className="meeting-automation-instructions">Custom instructions (optional)<textarea value={ui.sessionAutoAnalyzeCustomInstructions} onChange={(event) => setAutomation({ autoAnalyzeCustomInstructions: event.target.value })} /></label>
                </div>
              )}
            </div>,
            document.body,
          )}
        </div>
      </div>
      <div className="meeting-tools-row">
        <label className="meeting-tools-model">
          <span>Model:</span>
          <ReasoningModelPicker
            models={transcriptionModels}
            selectedModelId={selectedTranscriptionModelId}
            disabled={activeForSelection}
            ariaLabel="Transcription model"
            placeholder={ui.isLoadingModels ? 'Loading models…' : 'Choose a model'}
            onModelChange={(modelId) => {
              const model = ui.availableModels.find((candidate) => candidate.id === modelId);
              if (model) setPostProcessingModel(model.displayName);
            }}
          />
        </label>
        {!activeForSelection && (
          <div className="meeting-tools-actions">
            <button type="button" onClick={() => startPostProcessing('transcribe')} disabled={!ui.hasRecordedAudio || !ui.postProcessingModel}><WaveformIcon />Improve Transcript</button>
            <button type="button" onClick={() => startPostProcessing('diarize')} disabled={!ui.hasRecordedAudio}><PeopleIcon />Add Speaker Labels</button>
          </div>
        )}
      </div>

      {activeForSelection && (
        <div className="meeting-progress-row">
          <div className="meeting-progress-bar">
            <div className="meeting-progress-bar-fill" style={{ width: `${postProcessingPercent}%` }} />
          </div>
          <span className="meeting-progress-label">
            {ui.postProcessingStage} — {ui.postProcessingMessage}
            {ui.postProcessingSourceTotal > 1 && ui.postProcessingSourceIndex > 0 && ` (${ui.postProcessingSourceIndex}/${ui.postProcessingSourceTotal})`}
            {ui.postProcessingTotalTime > 0 && ` — ${formatSecondsWithClock(ui.postProcessingCurrentTime)} / ${formatSecondsWithClock(ui.postProcessingTotalTime)}`}
            {` — ${postProcessingPercent}%`}
            {ui.postProcessingETA > 0 && ` — ETA: ~${formatETA(ui.postProcessingETA)}`}
          </span>
        </div>
      )}

      {busyWithAnotherMeeting && (
        <p className="meeting-tools-owner-notice">Post-processing is running for another meeting in the background.</p>
      )}

      {ui.windowRetranscriptionStatus && ui.windowRetranscriptionStatus.phase !== 'completed' && (
        <p className="meeting-window-retranscription-status">{ui.windowRetranscriptionStatus.message}</p>
      )}

    </section>
  );
}

function formatSecondsWithClock(seconds: number): string {
  const normalizedSeconds = Math.max(0, seconds);
  return `${normalizedSeconds.toFixed(1)}s (${formatClockSeconds(Math.round(normalizedSeconds))})`;
}

function formatETA(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${remainingSeconds}s` : `${remainingSeconds}s`;
}

function SwitchControl({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="meeting-switch-control"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span className="meeting-switch-track" aria-hidden="true" /></label>;
}

function AutomationIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><circle cx="5.2" cy="6" r="2.1" /><circle cx="10.9" cy="10.3" r="2.1" /><path d="M5.2 2.6v1.3M5.2 8.1v1.3M1.8 6h1.3M7.3 6h1.3M10.9 6.9v1.3m0 4.2v1.3M7.5 10.3h1.3m4.2 0h1.3" /></svg>;
}

function WaveformIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><path d="M2 8h2l1-4 2 8 2-8 2 8 1-4h2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function PeopleIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><circle cx="5.5" cy="5.2" r="2.2" /><circle cx="11.2" cy="5.8" r="1.8" /><path d="M1.8 13c.3-2.5 1.6-3.8 3.7-3.8S9 10.5 9.3 13M9 9.4c2.8-.5 4.6.7 5 3.3" /></svg>;
}
