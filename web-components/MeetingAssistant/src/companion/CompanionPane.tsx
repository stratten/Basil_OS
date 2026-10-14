import { useState } from 'react';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import type { MeetingUIStateDTO } from '../bridge/types';
import { setAnalysisConfiguration } from '../bridge/meetingBridge';
import { PlayCircleIcon } from '../components/MeetingIcons';
import { groupedAnalysisModels } from '../lib/analysisModelOptions';
import CompanionAutoEnable from './CompanionAutoEnable';
import CompanionChat from './CompanionChat';
import CompanionFocusField from './CompanionFocusField';
import CompanionPaneHeader from './CompanionPaneHeader';
import CompanionItemCard from './CompanionItemCard';
import CompanionScreenShareNote from './CompanionScreenShareNote';
import CompanionSources from './CompanionSources';
import CompanionToggle, { type CompanionToggleProps } from './CompanionToggle';
import CompanionWatches from './CompanionWatches';
import { selectFeedItems } from './companionReducer';
import { companionLatencySummary, formatLatencySummary } from './companionLatency';
import { companionCapacityNotice, companionStatusLabel, type CompanionStatusTone } from './companionPaneState';
import type { CompanionController } from './useCompanion';
import type { CompanionGlobalSettingsController } from './useCompanionGlobalSettings';

const STATUS_DOT_CLASS: Record<CompanionStatusTone, string> = {
  off: '',
  on: ' meeting-connection-indicator--ready',
  busy: ' meeting-connection-indicator--ready',
  warn: ' meeting-connection-indicator--paused',
};

interface CompanionPaneProps {
  ui: MeetingUIStateDTO;
  controller: CompanionController;
  /** The one load of the global Companion preferences, shared with the Companion switch. */
  globalSettings: CompanionGlobalSettingsController;
  /** True when the pane's meeting is the one being recorded right now. */
  isTargetRecording: boolean;
  variant: 'embedded' | 'detached';
  onClose?: () => void;
  /** The detached window has no recording controls, so the pane carries the Companion switch itself. */
  toggle?: CompanionToggleProps;
}

export default function CompanionPane({ ui, controller, globalSettings, isTargetRecording, variant, onClose, toggle }: CompanionPaneProps) {
  const { state } = controller;
  const { timeline, status } = state;
  const [showDismissed, setShowDismissed] = useState(false);
  const [isEnabling, setIsEnabling] = useState(false);
  const statusView = companionStatusLabel(status);
  const capacityNotice = companionCapacityNotice(status);
  const feed = selectFeedItems(timeline.items, { includeDismissed: showDismissed });
  const dismissedCount = timeline.items.filter((item) => item.dismissed).length;
  const watchTopics = new Map(timeline.watches.map((watch) => [watch.id, watch.topic]));
  const modelOptions = groupedAnalysisModels(ui);
  const latency = companionLatencySummary(timeline.items);

  const turnOn = async () => {
    setIsEnabling(true);
    await controller.enable();
    setIsEnabling(false);
  };

  const sources = (canEdit: boolean) => (
    <CompanionSources
      roots={timeline.roots}
      pendingRoots={controller.pendingRoots}
      canEdit={canEdit}
      onAddPaths={controller.addRoots}
      onRemoveRoot={controller.removeRoot}
      onRemovePending={controller.removePendingRoot}
    />
  );

  const renderItem = (item: (typeof feed)[number]) => (
    <CompanionItemCard key={item.id} item={item} watchTopic={item.watch_id ? watchTopics.get(item.watch_id) ?? null : null} onFeedback={controller.sendFeedback} />
  );

  const renderBody = () => {
    if (state.phase === 'loading' || state.phase === 'idle') {
      return <p className="companion-state-note">{state.phase === 'loading' ? 'Loading the Companion…' : 'Waiting for the Basil backend…'}</p>;
    }
    if (state.phase === 'error') {
      return (
        <div className="meeting-history-load-more-error" role="alert">
          <span>{state.loadError ?? 'The Companion could not be loaded.'}</span>
          <button type="button" onClick={() => void controller.refresh()}>Retry</button>
        </div>
      );
    }
    if (!controller.isEnabled && isTargetRecording) {
      return (
        <div className="companion-off">
          <p>The Companion listens to the live transcript and surfaces insights, suggestions and answers as the conversation unfolds. Give it a folder or file and it can ground what it says in your own material.</p>
          <button type="button" className="meeting-record-button" disabled={isEnabling} onClick={() => void turnOn()}>
            <PlayCircleIcon />
            {isEnabling ? 'Turning On…' : 'Turn On Companion'}
          </button>
          {sources(true)}
          <CompanionAutoEnable {...globalSettings} />
          {feed.length > 0 && <h3 className="meeting-section-heading">Earlier in this meeting</h3>}
          {feed.map(renderItem)}
        </div>
      );
    }
    return (
      <>
        {!controller.isEnabled && <p className="companion-state-note">Saved Companion notes from this meeting. You can still pin, copy or dismiss them.</p>}
        <section className="companion-feed" aria-label="Companion feed">
          {feed.length === 0 && (
            <p className="companion-state-note">
              {status.mode === 'passive'
                ? 'Passive mode: the Companion answers when you ask.'
                : controller.isEnabled
                  ? 'Listening. Items appear here as the conversation gives the Companion something worth saying.'
                  : 'Nothing was surfaced in this meeting.'}
            </p>
          )}
          {feed.map(renderItem)}
          {dismissedCount > 0 && (
            <button type="button" className="meeting-history-load-more-button" onClick={() => setShowDismissed((current) => !current)}>
              {showDismissed ? 'Hide dismissed' : `Show dismissed (${dismissedCount})`}
            </button>
          )}
        </section>
        {sources(isTargetRecording)}
        <CompanionWatches watches={timeline.watches} canEdit={controller.isEnabled} onCreate={controller.createWatch} onCancel={controller.cancelWatch} />
        {controller.isEnabled && isTargetRecording && <CompanionFocusField value={status.focus} onSave={controller.setFocus} />}
      </>
    );
  };

  const showChat = state.phase === 'ready' && (controller.isEnabled || timeline.chat.length > 0);

  return (
    <aside className={`companion-pane companion-pane--${variant}`} aria-label="Companion">
      {variant === 'embedded' && <CompanionPaneHeader canDetach onCollapse={onClose} />}
      {variant === 'detached' && toggle && (
        <header className="meeting-tools-header companion-pane-header">
          <CompanionToggle {...toggle} />
        </header>
      )}
      <div className="meeting-status-row companion-status-row" role="status" title={status.capacity_reason ?? undefined}>
        <span className={`meeting-connection-indicator${STATUS_DOT_CLASS[statusView.tone]}`} aria-hidden="true" />
        <span className="meeting-status-message">{statusView.label}</span>
        {state.phase === 'ready' && latency && (
          <span className="meeting-transcription-state" title={`Time from the Companion deciding to speak until the item appeared, over the last ${latency.sampleCount} items`}>
            {formatLatencySummary(latency)}
          </span>
        )}
      </div>
      {isTargetRecording && (
        <label className="meeting-analysis-model-row">
          <span>Reasoning Model:</span>
          <ReasoningModelPicker
            models={modelOptions}
            selectedModelId={ui.selectedAnalysisModelId ?? undefined}
            disabled={ui.isAnalyzing || ui.isLoadingAnalysisModels}
            ariaLabel="Reasoning model"
            placeholder={ui.isLoadingAnalysisModels ? 'Loading models…' : 'Choose a model'}
            onModelChange={(modelId) => setAnalysisConfiguration({ modelId })}
          />
        </label>
      )}
      {capacityNotice && (
        <div className="meeting-status-row companion-notice-row" role="status">
          <span className="meeting-connection-indicator meeting-connection-indicator--paused" aria-hidden="true" />
          <span className="meeting-status-message">{capacityNotice}</span>
        </div>
      )}
      {controller.actionError && (
        <div className="meeting-history-load-more-error" role="alert">
          <span>{controller.actionError}</span>
          <button type="button" onClick={controller.clearActionError}>Dismiss</button>
        </div>
      )}
      {state.phase === 'ready' && state.loadError && (
        <div className="meeting-history-load-more-error" role="alert">
          <span>{state.loadError}</span>
          <button type="button" onClick={() => void controller.refresh()}>Retry</button>
        </div>
      )}
      <div className="companion-scroll">
        {isTargetRecording && state.phase === 'ready' && <CompanionScreenShareNote {...globalSettings} />}
        {renderBody()}
      </div>
      {showChat && (
        <CompanionChat
          messages={timeline.chat}
          drafts={state.drafts}
          pendingAssistantIds={state.pendingAssistantIds}
          canSend={controller.isEnabled}
          disabledMessage="Chat is available while the meeting is recording with the Companion on."
          onSend={controller.sendChat}
        />
      )}
    </aside>
  );
}
