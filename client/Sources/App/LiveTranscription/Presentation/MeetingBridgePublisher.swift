import AppKit
import Combine
import Foundation

/// Observes the shared `LiveTranscriptionViewModel` (and, while an analysis
/// result with proposals is open, its `MeetingActionProposalStore`), builds
/// version-1 DTOs, diffs each domain against the last value broadcast, and
/// invokes every attached presentation's sink with a
/// `MeetingBridgeEvent` whose `revision` is exactly one greater than the
/// previous event delivered to that same presentation. There are no timers;
/// every publish happens inside the `@Published` `didSet`/`sink` callback for
/// the mutation that already occurred on the main actor.
@MainActor
final class MeetingBridgePublisher {
    let viewModel: LiveTranscriptionViewModel
    private var proposalStore: MeetingActionProposalStore?
    var cancellables: Set<AnyCancellable> = []
    private var proposalCancellables: Set<AnyCancellable> = []

    private var sinks: [MeetingPresentationToken: (MeetingBridgeEvent) -> Void] = [:]
    private var meterSinks: [MeetingPresentationToken: (MeetingMeterPayload) -> Void] = [:]
    private var revisions: [MeetingPresentationToken: Int] = [:]
    var selectionGeneration = 0
    var lastSelectedMeetingId: String?

    private var lastUI: MeetingUIStateDTO?
    var lastTranscript: [TranscriptLineDTO] = []
    private var lastHistory: [MeetingListItemDTO] = []
    private var lastAnalysisHistory: [AnalysisMetadataEntryDTO] = []
    private var lastAnalysisResult: MeetingAnalysisResultDTO?
    private var lastProposals: [MeetingActionProposalDTO] = []
    private var audioProcessIconDataUrls: [String: String] = [:]

    init(viewModel: LiveTranscriptionViewModel) {
        self.viewModel = viewModel
        observe()
    }

    // MARK: - Attach / detach

    func attach(
        token: MeetingPresentationToken,
        sink: @escaping (MeetingBridgeEvent) -> Void,
        meterSink: @escaping (MeetingMeterPayload) -> Void
    ) {
        sinks[token] = sink
        meterSinks[token] = meterSink
        revisions[token] = 0
    }

    func detach(token: MeetingPresentationToken) {
        sinks.removeValue(forKey: token)
        meterSinks.removeValue(forKey: token)
        revisions.removeValue(forKey: token)
    }

    /// Sends the current full state as revision `0` to exactly one
    /// presentation (used both for the very first snapshot and for a
    /// late-attaching second window).
    func sendSnapshot(to token: MeetingPresentationToken) {
        guard let sink = sinks[token] else { return }
        let ui = buildUIState()
        lastUI = ui
        lastTranscript = buildTranscript()
        lastHistory = buildHistory()
        lastAnalysisHistory = buildAnalysisHistory()
        lastProposals = buildProposals()
        revisions[token] = 0
        sink(
            MeetingBridgeEvent(
                type: MeetingBridgeEventType.snapshot,
                revision: 0,
                selectionGeneration: selectionGeneration,
                ui: ui,
                transcript: lastTranscript,
                history: lastHistory,
                analysisHistory: lastAnalysisHistory,
                analysisResult: lastAnalysisResult,
                proposals: lastProposals,
                theme: stringPayload(AestheticWebPayload.themePayload()),
                fonts: stringPayload(AestheticWebPayload.fontPayload())
            )
        )
        meterSinks[token]?(
            MeetingMeterPayload(
                microphoneAudioLevel: viewModel.microphoneAudioLevel,
                systemAudioLevel: viewModel.systemAudioLevel
            )
        )
    }

    /// Publishes the current analysis result (called by
    /// `LiveTranscriptionViewModel+Analysis`'s coordinator delegation after a
    /// new analysis completes or an existing one is reopened) and rebinds the
    /// proposal store so proposal-outcome edits stream to every attached
    /// presentation.
    func publishAnalysisResult(_ result: MeetingAnalysisResultDTO, store: MeetingActionProposalStore) {
        lastAnalysisResult = result
        bindProposalStore(store)
        lastProposals = buildProposals()
        broadcast(MeetingBridgeEventType.analysisResultDelta) { event in
            event.analysisResult = result
        }
        broadcast(MeetingBridgeEventType.proposalsDelta) { event in
            event.proposals = self.lastProposals
        }
    }

    func publishValidationError(code: String, message: String) {
        broadcast(MeetingBridgeEventType.validationError) { event in
            event.validationErrorCode = code
            event.validationErrorMessage = message
        }
    }

    func advanceSelectionGeneration() {
        selectionGeneration += 1
        lastSelectedMeetingId = viewModel.selectedMeetingId
    }

    var currentAnalysisCustomInstructions: String? {
        lastAnalysisResult?.customInstructions
    }

    var currentAnalysisFilename: String? {
        lastAnalysisResult?.filename
    }

    private func bindProposalStore(_ store: MeetingActionProposalStore) {
        proposalStore = store
        proposalCancellables.removeAll()
        store.$statuses.sink { [weak self] _ in self?.emitProposalsDelta() }.store(in: &proposalCancellables)
        store.$drafts.sink { [weak self] _ in self?.emitProposalsDelta() }.store(in: &proposalCancellables)
        store.$errors.sink { [weak self] _ in self?.emitProposalsDelta() }.store(in: &proposalCancellables)
        store.$editingIds.sink { [weak self] _ in self?.emitProposalsDelta() }.store(in: &proposalCancellables)
        store.$submittedTaskIds.sink { [weak self] _ in self?.emitProposalsDelta() }.store(in: &proposalCancellables)
        store.$todoIds.sink { [weak self] _ in self?.emitProposalsDelta() }.store(in: &proposalCancellables)
        store.$liveStatuses.sink { [weak self] _ in self?.emitProposalsDelta() }.store(in: &proposalCancellables)
    }

    private func emitProposalsDelta() {
        let next = buildProposals()
        guard next != lastProposals else { return }
        lastProposals = next
        broadcast(MeetingBridgeEventType.proposalsDelta) { event in
            event.proposals = next
        }
    }

    // MARK: - Observation

    private func observe() {
        configureStreamingObservation()
        // A single coalesced re-check per main-actor turn is sufficient: every
        // `@Published` mutation on `viewModel` funnels through `objectWillChange`,
        // and reading `viewModel`'s current values after that turn always
        // reflects every field that changed together (e.g. `isAnalyzing` and
        // `analysisProgress` set in the same method call).
        viewModel.objectWillChange
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async { [weak self] in
                    self?.reconcile()
                }
            }
            .store(in: &cancellables)

        DateDisplayPreferenceStore.shared.$style
            .dropFirst()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.reconcile()
            }
            .store(in: &cancellables)

        Publishers.CombineLatest(
            viewModel.microphoneAudioLevelPublisher,
            viewModel.systemAudioLevelPublisher
        )
        .receive(on: DispatchQueue.main)
        .sink { [weak self] microphoneLevel, systemLevel in
            self?.publishMeter(
                MeetingMeterPayload(
                    microphoneAudioLevel: microphoneLevel,
                    systemAudioLevel: systemLevel
                )
            )
        }
        .store(in: &cancellables)
    }

    private func reconcile() {
        synchronizeSelectionGeneration()

        let ui = buildUIState()
        let normalizedUI = uiIgnoringMeterLevels(ui)
        if lastUI.map(uiIgnoringMeterLevels) != Optional(normalizedUI) {
            lastUI = ui
            broadcast(MeetingBridgeEventType.sessionDelta) { event in
                event.ui = ui
            }
        }

        let history = buildHistory()
        if history != lastHistory {
            lastHistory = history
            broadcast(MeetingBridgeEventType.historyDelta) { event in
                event.history = history
            }
        }

        let analysisHistory = buildAnalysisHistory()
        if analysisHistory != lastAnalysisHistory {
            lastAnalysisHistory = analysisHistory
            broadcast(MeetingBridgeEventType.analysisHistoryDelta) { event in
                event.analysisHistory = analysisHistory
            }
        }
    }

    /// Publishes live meter values on the dedicated unrevisioned channel.
    /// Meter-only changes are removed from the UI-state equality check above,
    /// so a paint signal never consumes a semantic event revision.
    private func publishMeter(_ payload: MeetingMeterPayload) {
        for sink in meterSinks.values {
            sink(payload)
        }
    }

    func broadcast(_ type: String, configure: (inout MeetingBridgeEvent) -> Void) {
        for (token, sink) in sinks {
            let next = (revisions[token] ?? 0) + 1
            revisions[token] = next
            var event = MeetingBridgeEvent(type: type, revision: next, selectionGeneration: selectionGeneration)
            configure(&event)
            sink(event)
        }
    }

    // MARK: - DTO builders

    private func buildUIState() -> MeetingUIStateDTO {
        var selectedProcessId: Int32?
        if #available(macOS 14.0, *) {
            selectedProcessId = viewModel.selectedAudioProcess?.id
        }
        return MeetingUIStateDTO(
            isRecording: viewModel.isRecording,
            statusMessage: viewModel.statusMessage,
            recordingTimeString: viewModel.recordingTimeString,
            connectionState: connectionStateString(viewModel.connectionState),
            meetingName: viewModel.meetingName,
            meetingPurpose: viewModel.meetingPurpose,
            meetingParticipants: viewModel.meetingParticipants,
            isSystemAudioAvailable: viewModel.isSystemAudioAvailable,
            availableAudioProcesses: viewModel.availableAudioProcesses.map(audioProcessGroupDTO),
            enableMicrophone: viewModel.enableMicrophone,
            systemAudioCaptureMode: viewModel.systemAudioCaptureMode.rawValue,
            selectedAudioProcessId: selectedProcessId,
            transcriptionState: viewModel.transcriptionState.rawValue,
            accumulatedDuration: viewModel.accumulatedDuration,
            lastTriggerReason: viewModel.lastTriggerReason,
            availableModels: viewModel.transcriptionModelOptions.map(transcriptionModelDTO),
            selectedModel: viewModel.selectedModel,
            isLoadingModels: viewModel.isLoadingModels,
            hasRecordedAudio: viewModel.hasRecordedAudio,
            hasTranscription: viewModel.hasTranscription,
            isPostProcessing: viewModel.isPostProcessing,
            postProcessingModel: viewModel.postProcessingModel,
            postProcessingProgress: viewModel.postProcessingProgress,
            postProcessingStage: viewModel.postProcessingStage,
            postProcessingMessage: PostProcessingProgressMath.progressLabel(
                message: viewModel.postProcessingMessage,
                sourceIndex: viewModel.postProcessingSourceIndex,
                sourceTotal: viewModel.postProcessingSourceTotal
            ),
            postProcessingCurrentTime: viewModel.postProcessingCurrentTime,
            postProcessingTotalTime: viewModel.postProcessingTotalTime,
            postProcessingETA: viewModel.postProcessingETA,
            postProcessingSourceIndex: viewModel.postProcessingSourceIndex,
            postProcessingSourceTotal: viewModel.postProcessingSourceTotal,
            postProcessingAggregateProgress: viewModel.postProcessingAggregateProgress,
            postProcessingStartedAutomatically: viewModel.postProcessingStartedAutomatically,
            activePostProcessingMeetingId: viewModel.activePostProcessingMeetingId,
            sessionAutoRetranscribeOnStop: viewModel.sessionAutoRetranscribeOnStop,
            sessionAutoRetranscribeDuringRecording: viewModel.sessionAutoRetranscribeDuringRecording,
            sessionAutoAnalyzeOnComplete: viewModel.sessionAutoAnalyzeOnComplete,
            sessionAutoAnalyzeModes: viewModel.sessionAutoAnalyzeModes,
            sessionAutoAnalyzeCustomInstructions: viewModel.sessionAutoAnalyzeCustomInstructions,
            sessionAutoAnalyzeTiming: viewModel.sessionAutoAnalyzeTiming,
            windowRetranscriptionStatus: viewModel.windowRetranscriptionStatus.map(windowRetranscriptionStatusDTO),
            isApplyingWindowedRetranscription: viewModel.isApplyingWindowedRetranscription,
            isAnalysisSectionExpanded: viewModel.isAnalysisSectionExpanded,
            selectedAnalysisModes: viewModel.selectedAnalysisModes.map(\.rawValue).sorted(),
            analysisCustomInstructions: viewModel.analysisCustomInstructions,
            selectedAnalysisModelId: viewModel.selectedAnalysisModelId,
            localAnalysisModels: viewModel.localAnalysisModels.map(reasoningModelDTO),
            apiAnalysisModels: viewModel.apiAnalysisModels.map(reasoningModelDTO),
            useApiModelsForAnalysis: viewModel.useApiModelsForAnalysis,
            isLoadingAnalysisModels: viewModel.isLoadingAnalysisModels,
            isAnalyzing: viewModel.isAnalyzing,
            analysisProgress: viewModel.analysisProgress,
            analysisMessage: viewModel.analysisMessage,
            currentAnalysisMode: viewModel.currentAnalysisMode,
            analysisJustCompleted: viewModel.analysisJustCompleted,
            analysisStartedAutomatically: viewModel.analysisStartedAutomatically,
            activeAnalysisMeetingId: viewModel.activeAnalysisMeetingId,
            isLoadingAnalysisHistory: viewModel.isLoadingAnalysisHistory,
            isLoadingAnalysisResult: viewModel.isLoadingAnalysisResult,
            analysisResultRequestedFilename: viewModel.analysisResultRequestedFilename,
            analysisResultLoadError: viewModel.analysisResultLoadError,
            isSidebarCollapsed: viewModel.isSidebarCollapsed,
            isLoadingMeetings: viewModel.isLoadingMeetings,
            isLoadingMoreMeetings: viewModel.isLoadingMoreMeetings,
            hasMoreMeetings: viewModel.hasMoreMeetings,
            meetingHistoryLoadMoreError: viewModel.meetingHistoryLoadMoreError,
            selectedMeetingId: viewModel.selectedMeetingId,
            displayedMeetingWorkOwnerId: viewModel.selectedMeetingId ?? viewModel.currentMeetingId,
            isViewingPastMeeting: viewModel.isViewingPastMeeting,
            meetingSearchText: viewModel.meetingSearchText,
            meetingSearchFilters: meetingSearchFiltersDTO(viewModel.meetingSearchFilters),
            microphoneAudioLevel: viewModel.microphoneAudioLevel,
            systemAudioLevel: viewModel.systemAudioLevel,
            microphoneInputRecoveryState: microphoneRecoveryStateString(viewModel.microphoneInputRecoveryState),
            microphoneInputRecoveryMessage: microphoneRecoveryMessage(viewModel.microphoneInputRecoveryState),
            isCapturePaused: viewModel.isCapturePaused,
            isLiveTranscriptionEnabled: viewModel.sessionLiveTranscriptionEnabled
        )
    }

    private func uiIgnoringMeterLevels(_ ui: MeetingUIStateDTO) -> MeetingUIStateDTO {
        var normalized = ui
        normalized.microphoneAudioLevel = 0
        normalized.systemAudioLevel = 0
        return normalized
    }

    func buildTranscript() -> [TranscriptLineDTO] {
        viewModel.transcriptionLines.map { line in
            TranscriptLineDTO(
                id: line.id,
                text: line.text,
                speakerId: line.speakerID,
                isInterim: line.isInterim,
                displayStart: line.displayStart,
                timelineStartSeconds: line.timelineStartSeconds,
                timelineEndSeconds: line.timelineEndSeconds,
                source: line.source?.rawValue,
                lineComplete: line.lineComplete
            )
        }
    }

    private func buildHistory() -> [MeetingListItemDTO] {
        viewModel.meetings.map { item in
            MeetingListItemDTO(
                id: item.id,
                name: item.name,
                purpose: item.purpose,
                participants: item.participants,
                startTime: item.startTime,
                endTime: item.endTime,
                durationSeconds: item.durationSeconds,
                isPostProcessed: item.isPostProcessed,
                analysisSummary: item.analysisSummary.map {
                    AnalysisSummaryDTO(
                        count: $0.count,
                        latestFilename: $0.latestFilename,
                        latestTimestamp: $0.latestTimestamp,
                        pendingActionCount: $0.pendingActionCount
                    )
                },
                sessionId: item.sessionId,
                audioSource: item.audioSource,
                members: item.members?.map {
                    MeetingMemberDTO(
                        id: $0.id,
                        source: $0.source,
                        isPostProcessed: $0.isPostProcessed,
                        startTime: $0.startTime,
                        durationSeconds: $0.durationSeconds,
                        timelineOffsetSeconds: $0.timelineOffsetSeconds,
                        recordingPartIndex: $0.recordingPartIndex
                    )
                },
                formattedDate: item.displayDate,
                shortFormattedDuration: item.shortFormattedDuration,
                relativeDateString: item.relativeDateString
            )
        }
    }

    private func meetingSearchFiltersDTO(_ filters: MeetingHistorySearchFilters) -> MeetingHistorySearchFiltersDTO {
        MeetingHistorySearchFiltersDTO(
            queryMode: filters.queryMode.rawValue,
            name: filters.name,
            nameMode: filters.nameMode.rawValue,
            purpose: filters.purpose,
            purposeMode: filters.purposeMode.rawValue,
            participants: filters.participants,
            participantsMode: filters.participantsMode.rawValue,
            transcript: filters.transcript,
            transcriptMode: filters.transcriptMode.rawValue,
            source: filters.source,
            sourceMode: filters.sourceMode.rawValue,
            startDate: filters.startDate,
            endDate: filters.endDate,
            processing: filters.processing.rawValue,
            analysis: filters.analysis.rawValue
        )
    }

    private func buildAnalysisHistory() -> [AnalysisMetadataEntryDTO] {
        viewModel.analysisHistory.map { entry in
            AnalysisMetadataEntryDTO(
                timestamp: entry.timestamp,
                filename: entry.filename,
                modes: entry.modes,
                modelUsed: entry.modelUsed,
                formattedDate: entry.formattedDate,
                modesDisplay: entry.modesDisplay,
                shortModelName: entry.shortModelName
            )
        }
    }

    private func buildProposals() -> [MeetingActionProposalDTO] {
        guard let proposalStore else { return [] }
        return proposalStore.proposals.map { proposal in
            MeetingActionProposalDTO(
                id: proposal.id,
                sourceActionItemIndex: proposal.sourceActionItemIndex,
                sourceActionItemIndexes: proposal.sourceActionItemIndexes,
                sourceTask: proposal.sourceTask,
                sourceContext: proposal.sourceContext,
                sourceTimestamp: proposal.sourceTimestamp,
                sourceSpeaker: proposal.sourceSpeaker,
                suggestedAgentTask: proposal.suggestedAgentTask,
                capabilityType: proposal.capabilityType,
                confidence: proposal.confidence,
                whyBasilCanHelp: proposal.whyBasilCanHelp,
                missingInformation: proposal.missingInformation,
                requiresUserConfirmation: proposal.requiresUserConfirmation,
                executionMode: proposal.executionMode,
                workspaceSource: proposal.workspaceSource,
                executionStatus: proposalStore.effectiveStatus(proposal),
                submittedAgentTaskId: proposalStore.submittedTaskIds[proposal.id],
                todoId: proposalStore.todoIds[proposal.id],
                todoStatus: proposalStore.todoStatuses[proposal.id],
                lastError: proposalStore.errors[proposal.id],
                isEditingDraft: proposalStore.isEditing(proposal),
                draftPrompt: proposalStore.currentPrompt(proposal),
                liveAgentStatus: proposalStore.liveStatuses[proposal.id]?.rawValue
            )
        }
    }

    private func audioProcessGroupDTO(_ group: AudioProcessGroup) -> AudioProcessGroupDTO {
        AudioProcessGroupDTO(
            id: group.id,
            title: group.title,
            processes: group.processes.map {
                AudioProcessDTO(
                    id: $0.id,
                    name: $0.name,
                    kind: $0.kind.rawValue,
                    audioActive: $0.audioActive,
                    bundleId: $0.bundleID,
                    iconDataUrl: audioProcessIconDataUrl(for: $0)
                )
            }
        )
    }

    private func audioProcessIconDataUrl(for process: AudioProcess) -> String? {
        let cacheKey = process.bundleURL?.path ?? process.bundleID ?? "kind:\(process.kind.rawValue)"
        if let cached = audioProcessIconDataUrls[cacheKey] {
            return cached
        }

        let size = NSSize(width: 24, height: 24)
        let renderedIcon = NSImage(size: size)
        renderedIcon.lockFocus()
        NSGraphicsContext.current?.imageInterpolation = .high
        process.icon.draw(
            in: NSRect(origin: .zero, size: size),
            from: .zero,
            operation: .copy,
            fraction: 1
        )
        renderedIcon.unlockFocus()

        guard let tiff = renderedIcon.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            return nil
        }

        let dataUrl = "data:image/png;base64,\(png.base64EncodedString())"
        audioProcessIconDataUrls[cacheKey] = dataUrl
        return dataUrl
    }

    private func reasoningModelDTO(_ model: ReasoningModelInfoVM) -> ReasoningModelInfoDTO {
        ReasoningModelInfoDTO(
            id: model.id,
            name: model.name,
            displayName: model.displayName,
            provider: model.provider,
            isApiModel: model.isApiModel,
            category: model.isApiModel && model.provider.lowercased() == "custom" ? "custom" : (model.isApiModel ? "api" : "local")
        )
    }

    private func transcriptionModelDTO(_ model: TranscriptionModelOption) -> TranscriptionModelInfoDTO {
        TranscriptionModelInfoDTO(
            id: model.id,
            name: model.displayName,
            displayName: model.displayName,
            provider: model.provider,
            category: model.isApiModel && model.provider?.lowercased() == "custom" ? "custom" : (model.isApiModel ? "api" : "local")
        )
    }

    private func windowRetranscriptionStatusDTO(_ status: WindowRetranscriptionStatus) -> WindowRetranscriptionStatusDTO {
        let phase: String
        switch status.phase {
        case .running: phase = "running"
        case .applying: phase = "applying"
        case .completed: phase = "completed"
        case .failed: phase = "failed"
        }
        return WindowRetranscriptionStatusDTO(
            id: status.id.uuidString,
            source: status.source.rawValue,
            start: status.start,
            end: status.end,
            phase: phase,
            message: status.message
        )
    }

    private func connectionStateString(_ state: ConnectionState) -> String {
        switch state {
        case .ready: return "ready"
        case .recording: return "recording"
        case .error: return "error"
        case .connecting: return "connecting"
        }
    }

    private func microphoneRecoveryStateString(_ state: MicrophoneInputRecoveryState) -> String {
        switch state {
        case .idle: return "idle"
        case .reconnecting: return "reconnecting"
        case .failed: return "failed"
        }
    }

    private func microphoneRecoveryMessage(_ state: MicrophoneInputRecoveryState) -> String? {
        if case .failed(let message) = state { return message }
        return nil
    }

    private func stringPayload(_ payload: [String: Any]) -> [String: String] {
        payload.reduce(into: [String: String]()) { result, pair in
            result[pair.key] = "\(pair.value)"
        }
    }
}

extension MeetingBridgePublisher {
    func updateProposalDraft(proposalId: String, draft: String) {
        guard let proposalStore, let proposal = proposalStore.proposals.first(where: { $0.id == proposalId }) else { return }
        proposalStore.drafts[proposal.id] = draft
    }

    func setProposalEditing(proposalId: String, editing: Bool) {
        guard let proposalStore, let proposal = proposalStore.proposals.first(where: { $0.id == proposalId }) else { return }
        if editing {
            proposalStore.editingIds.insert(proposal.id)
        } else {
            proposalStore.editingIds.remove(proposal.id)
        }
    }

    func submitProposal(proposalId: String) {
        guard let proposalStore, let proposal = proposalStore.proposals.first(where: { $0.id == proposalId }) else { return }
        Task { await proposalStore.submit(proposal) }
    }

    func startProposalNow(proposalId: String) {
        guard let proposalStore, let proposal = proposalStore.proposals.first(where: { $0.id == proposalId }) else { return }
        Task { await proposalStore.startNow(proposal) }
    }

    func submitAllEligibleProposals() {
        guard let proposalStore else { return }
        Task { await proposalStore.submitAllEligible() }
    }

    func dismissProposal(proposalId: String) {
        guard let proposalStore, let proposal = proposalStore.proposals.first(where: { $0.id == proposalId }) else { return }
        proposalStore.dismiss(proposal)
    }

    func restoreProposal(proposalId: String) {
        guard let proposalStore, let proposal = proposalStore.proposals.first(where: { $0.id == proposalId }) else { return }
        proposalStore.restore(proposal)
    }
}
