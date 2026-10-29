import { useCallback, useEffect, useRef, useState } from 'react';
import PresenceRegion from '../../../shared/PresenceRegion';
import UndoNotice from '../../../shared/UndoNotice';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import type { MeetingUIStateDTO } from '../bridge/types';
import { setAnalysisConfiguration } from '../bridge/meetingBridge';
import MeetingSwitch from '../components/MeetingSwitch';
import { PlayCircleIcon } from '../components/MeetingIcons';
import { groupedAnalysisModels } from '../lib/analysisModelOptions';
import CompanionAutoEnable from './CompanionAutoEnable';
import CompanionChatEntry, { COMPANION_CONTINUE_PROMPT } from './CompanionChatEntry';
import CompanionComposer from './CompanionComposer';
import CompanionAuditSection from './CompanionAuditSection';
import CompanionConsideredBar from './CompanionConsideredBar';
import CompanionConsideredRow from './CompanionConsideredRow';
import CompanionFocusField from './CompanionFocusField';
import CompanionPaneHeader from './CompanionPaneHeader';
import CompanionPinnedStrip from './CompanionPinnedStrip';
import CompanionItemCard from './CompanionItemCard';
import CompanionKindFilter from './CompanionKindFilter';
import CompanionProposalCard from './CompanionProposalCard';
import CompanionProposalSettings from './CompanionProposalSettings';
import CompanionScreenShareNote from './CompanionScreenShareNote';
import CompanionSettingsSection from './CompanionSettingsSection';
import CompanionSources from './CompanionSources';
import CompanionStream, { type CompanionStreamHandle } from './CompanionStream';
import CompanionToggle, { type CompanionToggleProps } from './CompanionToggle';
import CompanionWatches from './CompanionWatches';
import CompanionWorkingRow from './CompanionWorkingRow';
import { chatResearchTarget, replyQuote } from './companionChatResearch';
import { COMPANION_FOCUS_FRESH_MS, useCompanionLinks } from './companionLinks';
import { companionLatencySummary, formatLatencySummary } from './companionLatency';
import { canInvestigate, investigationQuestionFromItem, proposalContextText, unresolvedInvestigations } from './companionProposals';
import { companionCapacityNotice, companionDisplayLabel, companionNeedsSetup, companionSettingsSummary, companionStatusLabel, type CompanionStatusTone } from './companionPaneState';
import { countKindFilters, hideFoldedAnswers, itemMatchesKindFilter, selectChatPairs, selectCompanionStream, selectPinnedItems, selectProposalsAwaitingDecision, selectUnseenEntries, type CompanionStreamEntry } from './companionStreamSelectors';
import { companionTargetMeetingId } from './companionTarget';
import { getCompanionView, updateCompanionView, useCompanionView } from './companionViewStore';
import type { CompanionFeedbackAction } from './types';
import type { CompanionController } from './useCompanion';
import { useLastChecked } from './useLastChecked';
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
  const streamRef = useRef<CompanionStreamHandle>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const [isEnabling, setIsEnabling] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [undo, setUndo] = useState<{ itemId: string; key: number } | null>(null);
  const [pendingReveal, setPendingReveal] = useState<string | null>(null);
  const undoCount = useRef(0);
  const isReady = state.phase === 'ready';
  const meetingId = companionTargetMeetingId(ui);
  const { view, update: updateView, markSeen } = useCompanionView(meetingId, isReady ? state.baselineSeq : null);
  const statusView = companionStatusLabel(status);
  const capacityNotice = companionCapacityNotice(status);
  const fullStream = selectCompanionStream(timeline, { includeDismissed: showDismissed, kindFilter: view.kindFilter, showConsidered: view.showConsidered, drafts: state.drafts, pendingAssistantIds: state.pendingAssistantIds });
  // A folded question hides its answer, so the stream (and the "new" count, which only counts rows that can be seen) works from the visible rows.
  const chatPairs = selectChatPairs(fullStream);
  const stream = hideFoldedAnswers(fullStream, chatPairs, view.collapsedItemIds);
  const kindCounts = countKindFilters(timeline.items);
  const lastCheckedAt = useLastChecked(status.evaluating);
  const unseen = selectUnseenEntries(stream, view.lastSeenSeq ?? state.baselineSeq);
  const pinned = selectPinnedItems(timeline.items);
  const awaitingDecision = selectProposalsAwaitingDecision(timeline.items);
  const dismissedCount = timeline.items.filter((item) => item.dismissed).length;
  const watchTopics = new Map(timeline.watches.map((watch) => [watch.id, watch.topic]));
  const modelOptions = groupedAnalysisModels(ui);
  const latency = companionLatencySummary(timeline.items);
  const statusTooltip = [status.capacity_reason, isReady && latency ? `${formatLatencySummary(latency)}. Measured from the Companion deciding to speak until the item appeared, over the last ${latency.sampleCount} items.` : null].filter(Boolean).join(' ') || undefined;

  useEffect(() => {
    setUndo(null);
    setPendingReveal(null);
  }, [meetingId]);

  // The pane appears the moment recording starts, and a first run with nothing attached opens the settings so sources can be added before anyone speaks. Once the transcript actually begins (the meeting clock moves off zero) a settings section the reader has not chosen either way folds up, so the stream gets the room. A choice the reader made, open or closed, is left alone, and a pane that first loads with the meeting already under way does not count as a start.
  const meetingHadBegun = useRef<boolean | null>(null);
  useEffect(() => {
    if (!isReady || !isTargetRecording) return;
    const begun = status.latest_meeting_time > 0;
    if (meetingHadBegun.current === null) {
      meetingHadBegun.current = begun;
      return;
    }
    if (!meetingHadBegun.current && begun) {
      meetingHadBegun.current = true;
      if (view.settingsOpen === null) updateView({ settingsOpen: false });
    }
  }, [isReady, isTargetRecording, status.latest_meeting_time]);

  // Scroll to a card once it is in the stream. A card the current filter hides is revealed by switching the filter to All first; a card that is not there at all (dismissed, or not loaded) is given up on instead of waiting for it forever.
  useEffect(() => {
    if (pendingReveal === null) return;
    // A folded card is opened first; the change re-runs this effect, which then scrolls to the full-height card.
    if (view.collapsedItemIds.includes(pendingReveal)) {
      updateView({ collapsedItemIds: view.collapsedItemIds.filter((id) => id !== pendingReveal) });
      return;
    }
    if (streamRef.current?.scrollToKey(`item:${pendingReveal}`)) setPendingReveal(null);
    else if (view.kindFilter === 'all') setPendingReveal(null);
  }, [pendingReveal, stream.length, view.kindFilter, view.collapsedItemIds]);

  // Folding a note changes only the reader's view of it: the note keeps its place in the stream.
  const toggleCollapsed = useCallback((itemId: string) => {
    const current = getCompanionView(meetingId).collapsedItemIds;
    updateCompanionView(meetingId, {
      collapsedItemIds: current.includes(itemId) ? current.filter((id) => id !== itemId) : [...current, itemId],
    });
  }, [meetingId]);

  const revealItem = (itemId: string) => {
    const target = timeline.items.find((candidate) => candidate.id === itemId);
    if (target && !itemMatchesKindFilter(target, view.kindFilter)) updateView({ kindFilter: 'all' });
    setPendingReveal(itemId);
  };

  const giveFeedback = async (itemId: string, action: CompanionFeedbackAction): Promise<boolean> => {
    const saved = await controller.sendFeedback(itemId, action);
    if (saved && action === 'dismissed') {
      undoCount.current += 1;
      setUndo({ itemId, key: undoCount.current });
    }
    return saved;
  };

  const undoDismissal = async () => {
    if (undo === null) return;
    const { itemId } = undo;
    setUndo(null);
    if (await controller.sendFeedback(itemId, 'restored')) revealItem(itemId);
  };

  // A request from the transcript to show one card. A request that was already stale when the pane mounted is left alone. While the timeline is still loading the card may not exist yet, so the attempt repeats until the pane is ready and then stops, whether or not the card was found (a dismissed card stays hidden).
  const links = useCompanionLinks();
  const companionFocus = links?.companionFocus ?? null;
  const handledFocusKey = useRef<string | null>(companionFocus !== null && Date.now() - companionFocus.issuedAt > COMPANION_FOCUS_FRESH_MS ? companionFocus.key : null);
  useEffect(() => {
    if (companionFocus === null || handledFocusKey.current === companionFocus.key) return;
    // A folded card is opened first so the transcript's jump lands on the whole note; the change re-runs this effect.
    if (view.collapsedItemIds.includes(companionFocus.itemId)) {
      updateView({ collapsedItemIds: view.collapsedItemIds.filter((id) => id !== companionFocus.itemId) });
      return;
    }
    const found = streamRef.current?.scrollToKey(`item:${companionFocus.itemId}`) === true;
    if (found || isReady) handledFocusKey.current = companionFocus.key;
  }, [companionFocus, isReady, stream.length, view.collapsedItemIds]);

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

  // A live Companion researches while its switch is on. A meeting that is no longer being recorded can still be researched on request, so Investigate stays on its cards after the call ends.
  const researchOn = controller.isEnabled ? status.investigate : isReady && !isTargetRecording && !status.live;
  const pendingInvestigations = unresolvedInvestigations(timeline);
  const lastInvestigation = pendingInvestigations.length > 0 ? pendingInvestigations[pendingInvestigations.length - 1] : null;

  // The buttons follow the user's own capability settings; before those load, both are offered and the backend refuses a disabled one.
  const capabilities = globalSettings.settings?.proposal_capabilities;
  const allowedActions = (['todo', 'agent_task'] as const).filter((action) => capabilities === undefined || capabilities.includes(action));
  const actionCards = new Map<string, (typeof timeline.items)[number]>();
  for (const candidate of timeline.items) {
    if (candidate.source_item_id && candidate.proposal && !candidate.dismissed) actionCards.set(candidate.source_item_id, candidate);
  }

  const renderItem = (item: (typeof timeline.items)[number]) =>
    item.kind === 'proposal' ? (
      <CompanionProposalCard item={item} contextText={proposalContextText(timeline.items, item)} onDecide={controller.decideProposal} />
    ) : (
      <CompanionItemCard
        item={item}
        watchTopic={item.watch_id ? watchTopics.get(item.watch_id) ?? null : null}
        onFeedback={giveFeedback}
        canInvestigate={researchOn && canInvestigate(item)}
        onInvestigate={(target) => void controller.investigate(investigationQuestionFromItem(target))}
        replyQuote={replyQuote(timeline, item.reply_to_message_id)}
        linkedAction={actionCards.get(item.id) ?? null}
        allowedActions={allowedActions}
        onAction={controller.actOnItem}
        collapsed={view.collapsedItemIds.includes(item.id)}
        onToggleCollapsed={toggleCollapsed}
      />
    );

  const lastChatId = timeline.chat.length > 0 ? timeline.chat[timeline.chat.length - 1].id : null;
  const answerInFlight = Object.keys(state.drafts).length > 0 || state.pendingAssistantIds.length > 0;

  const continueAnswer = async () => {
    if (continuing || !controller.isEnabled) return;
    setContinuing(true);
    await controller.sendChat(COMPANION_CONTINUE_PROMPT);
    setContinuing(false);
  };

  const renderEntry = (entry: CompanionStreamEntry) => {
    if (entry.type === 'item') return renderItem(entry.item);
    if (entry.type === 'considered') return <CompanionConsideredRow event={entry.event} />;
    const canContinue = entry.type === 'chat' && controller.isEnabled && entry.message.role === 'assistant' && entry.message.truncated && entry.message.id === lastChatId && !answerInFlight;
    const research = entry.type === 'chat' && researchOn && !answerInFlight ? chatResearchTarget(timeline, entry.message) : null;
    // A question with a saved answer, and that answer, fold together under the question's message id.
    const pairedQuestionId = entry.type !== 'chat' ? null : entry.message.role === 'user' ? (chatPairs.answerKeysByQuestion.has(entry.message.id) ? entry.message.id : null) : chatPairs.questionByAnswerKey.get(entry.key) ?? null;
    const fold = pairedQuestionId === null ? null : { folded: view.collapsedItemIds.includes(pairedQuestionId), onToggle: () => toggleCollapsed(pairedQuestionId) };
    return (
      <CompanionChatEntry
        entry={entry}
        canContinue={canContinue}
        busy={continuing}
        onContinue={() => void continueAnswer()}
        onLookIntoThis={research ? () => void controller.investigate(research.question, research.replyToMessageId) : null}
        fold={fold}
      />
    );
  };

  const modelRow = isTargetRecording && (
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
  );

  const showOffState = isReady && !controller.isEnabled && isTargetRecording;
  const needsSetup = companionNeedsSetup({ timeline, pendingSourceCount: controller.pendingRoots.length });
  const settingsOpen = view.settingsOpen ?? (isTargetRecording && needsSetup);

  const renderOffState = () => {
    const earlier = stream.filter((entry): entry is Extract<CompanionStreamEntry, { type: 'item' }> => entry.type === 'item');
    return (
      <div className="companion-scroll">
        <div className="companion-off">
          <p>The Companion listens to the live transcript and surfaces insights, suggestions and answers as the conversation unfolds. Give it a folder or file and it can ground what it says in your own material.</p>
          <button type="button" className="meeting-record-button" disabled={isEnabling} onClick={() => void turnOn()}>
            <PlayCircleIcon />
            {isEnabling ? 'Turning On…' : 'Turn On Companion'}
          </button>
          {modelRow}
          {sources(true)}
          <CompanionAutoEnable {...globalSettings} />
          <CompanionProposalSettings {...globalSettings} />
          {earlier.length > 0 && <h3 className="meeting-section-heading">Earlier in this meeting</h3>}
          {earlier.map((entry) => (
            <div key={entry.key} className="companion-stream-row">{renderItem(entry.item)}</div>
          ))}
        </div>
      </div>
    );
  };

  const renderEmptyNote = () => (
    <p className="companion-state-note">
      {status.mode === 'passive'
        ? 'Passive mode: the Companion answers when you ask.'
        : controller.isEnabled
          ? 'Listening. Items appear here as the conversation gives the Companion something worth saying.'
          : 'Nothing was surfaced in this meeting.'}
    </p>
  );

  const renderBody = () => {
    if (state.phase === 'loading' || state.phase === 'idle') {
      return (
        <div className="companion-scroll">
          <p className="companion-state-note">{state.phase === 'loading' ? 'Loading the Companion…' : 'Waiting for the Basil backend…'}</p>
        </div>
      );
    }
    if (state.phase === 'error') {
      return (
        <div className="companion-scroll">
          <div className="meeting-history-load-more-error" role="alert">
            <span>{state.loadError ?? 'The Companion could not be loaded.'}</span>
            <button type="button" onClick={() => void controller.refresh()}>Retry</button>
          </div>
        </div>
      );
    }
    if (showOffState) return renderOffState();
    return (
      <CompanionStream
        ref={streamRef}
        entries={stream}
        renderEntry={renderEntry}
        ready={isReady}
        baselineSeq={state.baselineSeq}
        unseen={unseen}
        onSeen={markSeen}
        active
        empty={renderEmptyNote()}
        lead={!controller.isEnabled ? <p className="companion-state-note">Saved Companion notes from this meeting. You can still pin, copy or dismiss them, or have the Companion investigate one.</p> : null}
        working={
          controller.isEnabled || status.investigating > 0 ? (
            <CompanionWorkingRow evaluating={status.evaluating} investigating={status.investigating} question={lastInvestigation?.question || null} onStop={controller.stopInvestigations} />
          ) : null
        }
        footer={
          dismissedCount > 0 ? (
            <button type="button" className="meeting-history-load-more-button companion-dismissed-toggle" onClick={() => setShowDismissed((current) => !current)}>
              {showDismissed ? 'Hide dismissed' : `Show dismissed (${dismissedCount})`}
            </button>
          ) : null
        }
      />
    );
  };

  const showComposer = isReady && (controller.isEnabled || timeline.chat.length > 0);
  const composerAttention = answerInFlight ? 'Answering…' : unseen.length > 0 ? `${unseen.length} new` : null;
  const showSettings = isReady && !showOffState;

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
        <span className="meeting-status-message" title={statusTooltip}>{companionDisplayLabel(statusView.label, lastCheckedAt)}</span>
      </div>
      {showSettings && (
        <CompanionSettingsSection
          open={settingsOpen}
          onToggle={() => updateView({ settingsOpen: !settingsOpen })}
          summary={companionSettingsSummary({ timeline, pendingSourceCount: controller.pendingRoots.length, researchOn: controller.isEnabled && isTargetRecording ? status.investigate : null })}
        >
          {modelRow}
          {sources(true)}
          <CompanionWatches watches={timeline.watches} canEdit={controller.isEnabled} onCreate={controller.createWatch} onCancel={controller.cancelWatch} />
          {controller.isEnabled && isTargetRecording && (
            <div className="companion-research-switch">
              <MeetingSwitch label="Research automatically" checked={status.investigate} onChange={(next) => void controller.setInvestigate(next)} />
            </div>
          )}
          {isTargetRecording && <CompanionProposalSettings {...globalSettings} />}
          {controller.isEnabled && isTargetRecording && <CompanionFocusField value={status.focus} onSave={controller.setFocus} />}
        </CompanionSettingsSection>
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
      {isReady && state.loadError && (
        <div className="meeting-history-load-more-error" role="alert">
          <span>{state.loadError}</span>
          <button type="button" onClick={() => void controller.refresh()}>Retry</button>
        </div>
      )}
      {isReady && !showOffState && awaitingDecision.length > 0 && (
        <button type="button" className="companion-decision-notice" onClick={() => revealItem(awaitingDecision[0].id)}>
          Needs your decision ({awaitingDecision.length})
        </button>
      )}
      {!showOffState && (
        <PresenceRegion visible={pinned.length > 0} className="basil-presence">
          <CompanionPinnedStrip
            items={pinned}
            open={view.pinnedOpen}
            onToggle={() => updateView({ pinnedOpen: !view.pinnedOpen })}
            onJump={revealItem}
          />
        </PresenceRegion>
      )}
      {isReady && !showOffState && kindCounts.all > 0 && (
        <>
          <CompanionKindFilter value={view.kindFilter} counts={kindCounts} onChange={(kindFilter) => updateView({ kindFilter })} />
          {view.kindFilter !== 'all' && kindCounts[view.kindFilter] === 0 && <p className="companion-state-note">Nothing here yet. Choose All to see everything.</p>}
        </>
      )}
      {isReady && !showOffState && timeline.evaluationTotal > 0 && (
        <CompanionConsideredBar
          total={timeline.evaluationTotal}
          spoke={timeline.items.filter((item) => item.trigger !== 'investigation' && item.kind !== 'proposal').length}
          shown={view.showConsidered}
          onToggle={(showConsidered) => updateView({ showConsidered })}
        />
      )}
      {isReady && !showOffState && (timeline.evaluationTotal > 0 || timeline.audit !== null) && (
        <CompanionAuditSection
          audit={timeline.audit}
          auditing={status.auditing === true}
          isRecording={isTargetRecording}
          failureMessage={timeline.lastError?.code === 'audit_failed' ? timeline.lastError.message : null}
          researchOn={researchOn}
          allowedActions={allowedActions}
          actionCards={actionCards}
          onRun={controller.runAudit}
          onInvestigate={(question) => void controller.investigate(question)}
          onAction={controller.actOnItem}
          onMark={controller.sendFeedback}
        />
      )}
      {isTargetRecording && isReady && <div className="companion-fixed-note"><CompanionScreenShareNote {...globalSettings} /></div>}
      {renderBody()}
      {undo !== null && (
        <div className="companion-undo-row">
          <UndoNotice noticeKey={undo.key} message="Note dismissed." onAction={() => void undoDismissal()} onExpire={() => setUndo(null)} />
        </div>
      )}
      {showComposer && (
        <CompanionComposer
          canSend={controller.isEnabled}
          disabledMessage="Chat is available while the meeting is recording with the Companion on."
          onSend={controller.sendChat}
          collapsed={view.composerCollapsed}
          onCollapsedChange={(collapsed) => updateView({ composerCollapsed: collapsed })}
          attentionLabel={composerAttention}
          busy={continuing}
        />
      )}
    </aside>
  );
}
