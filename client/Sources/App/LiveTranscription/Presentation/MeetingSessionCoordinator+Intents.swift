import AppKit
import Foundation

extension MeetingSessionCoordinator {
    /// Single validated entry point for every non-chrome intent forwarded by
    /// any attached WebKit presentation. This is the only place a React
    /// intent is allowed to mutate `viewModel`; every case validates its
    /// payload against current server-confirmed state before acting, and
    /// silently drops (after a debug log) anything malformed or stale rather
    /// than throwing into the UI.
    func handleWebIntent(_ intent: MeetingBridgeIntent, payload: [String: Any]) {
        guard let viewModel else { return }
        switch intent {
        case .toggleRecording:
            if viewModel.isRecording {
                viewModel.stopRecording()
            } else {
                guard !viewModel.isViewingPastMeeting,
                      viewModel.transcriptionState != .loadingModels else {
                    publishValidationError("recording_unavailable", "Resume the selected meeting or start a new meeting first.")
                    return
                }
                viewModel.startRecording()
            }
        case .startNewMeeting:
            guard !viewModel.isRecording else {
                publishValidationError("recording_active", "End the active meeting before starting a new one.")
                return
            }
            bridgePublisher?.advanceSelectionGeneration()
            Task { await viewModel.startNewMeeting() }
        case .resumeMeeting:
            guard viewModel.isViewingPastMeeting,
                  !viewModel.isRecording,
                  viewModel.transcriptionState != .loadingModels else {
                publishValidationError("resume_unavailable", "That meeting cannot be resumed right now.")
                return
            }
            Task { await viewModel.resumeSelectedMeeting() }
        case .selectMeeting:
            guard let meetingId = payload["meetingId"] as? String,
                  viewModel.meetings.contains(where: { $0.id == meetingId }) else {
                publishValidationError("stale_meeting", "That meeting is no longer available.")
                return
            }
            Task { await viewModel.selectMeeting(meetingId) }
        case .deleteMeeting:
            guard let meetingId = payload["meetingId"] as? String,
                  viewModel.meetings.contains(where: { $0.id == meetingId }) else {
                publishValidationError("stale_meeting", "That meeting is no longer available.")
                return
            }
            guard !viewModel.isAnalyzing || viewModel.activeAnalysisMeetingId != meetingId else {
                publishValidationError("analysis_active", "That meeting cannot be deleted while its analysis is in progress.")
                return
            }
            Task { await viewModel.deleteMeeting(meetingId) }
        case .setSidebarCollapsed:
            guard let collapsed = payload["collapsed"] as? Bool else {
                publishValidationError("invalid_sidebar_state", "The sidebar state was malformed.")
                return
            }
            viewModel.setSidebarCollapsed(collapsed)
        case .setMeetingSearch:
            guard let text = payload["text"] as? String else {
                publishValidationError("invalid_search", "The meeting search text was malformed.")
                return
            }
            viewModel.meetingHistoryRequestGeneration &+= 1
            viewModel.meetingSearchText = text
            viewModel.triggerMeetingSearch()
        case .setMeetingSearchFilters:
            guard let filters = meetingHistorySearchFilters(from: payload) else {
                publishValidationError("invalid_search_filters", "The meeting search filters were malformed.")
                return
            }
            viewModel.meetingHistoryRequestGeneration &+= 1
            viewModel.meetingSearchFilters = filters
            viewModel.triggerMeetingSearch()
        case .loadMoreMeetings:
            Task { await viewModel.loadMoreMeetingHistory() }
        case .updateMetadata:
            guard optionalString("name", in: payload) != .invalid,
                  optionalString("purpose", in: payload) != .invalid,
                  optionalString("participants", in: payload) != .invalid else {
                publishValidationError("invalid_metadata", "Meeting metadata was malformed.")
                return
            }
            if case .value(let name) = optionalString("name", in: payload) { viewModel.meetingName = name }
            if case .value(let purpose) = optionalString("purpose", in: payload) { viewModel.meetingPurpose = purpose }
            if case .value(let participants) = optionalString("participants", in: payload) { viewModel.meetingParticipants = participants }
            viewModel.scheduleMeetingMetadataSave()
        case .setAudioSource:
            guard !viewModel.isRecording, !viewModel.isViewingPastMeeting else {
                publishValidationError("audio_source_locked", "Audio sources cannot be changed while recording or viewing a past meeting.")
                return
            }
            let requestedMicrophone: Bool?
            if payload.keys.contains("enableMicrophone") {
                guard let value = payload["enableMicrophone"] as? Bool else {
                    publishValidationError("invalid_audio_source", "The microphone selection was malformed.")
                    return
                }
                requestedMicrophone = value
            } else {
                requestedMicrophone = nil
            }

            let requestedMode: SystemAudioCaptureMode?
            if payload.keys.contains("captureMode") {
                guard let modeString = payload["captureMode"] as? String else {
                    publishValidationError("invalid_audio_mode", "That audio capture mode is not supported.")
                    return
                }
                guard let mode = SystemAudioCaptureMode(rawValue: modeString) else {
                    publishValidationError("invalid_audio_mode", "That audio capture mode is not supported.")
                    return
                }
                requestedMode = mode
            } else {
                requestedMode = nil
            }

            var requestedProcess: AudioProcess?
            if payload.keys.contains("processId") {
                guard let processId = int32Value(payload["processId"]) else {
                    publishValidationError("invalid_process", "That app selection was malformed.")
                    return
                }
                let allProcesses = viewModel.availableAudioProcesses.flatMap(\.processes)
                if let match = allProcesses.first(where: { $0.id == processId && $0.audioActive }) {
                    requestedProcess = match
                } else {
                    bridgePublisher?.publishValidationError(
                        code: "stale_process",
                        message: "That app is no longer available."
                    )
                    return
                }
            }

            if let requestedMicrophone {
                viewModel.enableMicrophone = requestedMicrophone
            }
            if let requestedMode {
                viewModel.systemAudioCaptureMode = requestedMode
            }
            if let requestedProcess, #available(macOS 14.0, *) {
                viewModel.setSelectedAudioProcess(requestedProcess)
            }
        case .setPostProcessingModel:
            guard !viewModel.isPostProcessing,
                  let model = payload["model"] as? String,
                  viewModel.availableModels.contains(model) else {
                publishValidationError("invalid_post_processing_model", "That transcript model is not available.")
                return
            }
            viewModel.postProcessingModel = model
        case .startPostProcessing:
            guard !viewModel.isRecording,
                  viewModel.hasRecordedAudio,
                  !viewModel.isPostProcessing,
                  let operation = payload["operation"] as? String,
                  ["transcribe", "diarize"].contains(operation) else {
                publishValidationError("post_processing_unavailable", "Transcript processing cannot start in the current state.")
                return
            }
            Task { await viewModel.startPostProcessing(operation: operation, startedAutomatically: false) }
        case .setAutomation:
            let autoRetranscribeOnStop = optionalBool("autoRetranscribeOnStop", in: payload)
            let autoRetranscribeDuringRecording = optionalBool("autoRetranscribeDuringRecording", in: payload)
            let autoAnalyzeOnComplete = optionalBool("autoAnalyzeOnComplete", in: payload)
            let instructions = optionalString("autoAnalyzeCustomInstructions", in: payload)
            guard autoRetranscribeOnStop != .invalid,
                  autoRetranscribeDuringRecording != .invalid,
                  autoAnalyzeOnComplete != .invalid,
                  instructions != .invalid else {
                publishValidationError("invalid_automation", "The automation configuration was malformed.")
                return
            }

            var validatedModes: [String]?
            if payload.keys.contains("autoAnalyzeModes") {
                guard let modes = payload["autoAnalyzeModes"] as? [String] else {
                    publishValidationError("invalid_automation_mode", "One or more automatic analysis modes are unsupported.")
                    return
                }
                let validModes = modes.filter { AnalysisMode(rawValue: $0) != nil && $0 != AnalysisMode.custom.rawValue }
                guard validModes.count == modes.count else {
                    publishValidationError("invalid_automation_mode", "One or more automatic analysis modes are unsupported.")
                    return
                }
                validatedModes = validModes
            }

            var validatedTiming: String?
            if payload.keys.contains("autoAnalyzeTiming") {
                guard let timing = payload["autoAnalyzeTiming"] as? String else {
                    publishValidationError("invalid_analysis_timing", "Automatic analysis timing must be before or after re-transcription.")
                    return
                }
                guard ["before", "after"].contains(timing) else {
                    publishValidationError("invalid_analysis_timing", "Automatic analysis timing must be before or after re-transcription.")
                    return
                }
                validatedTiming = timing
            }

            if case .value(let value) = autoRetranscribeOnStop { viewModel.sessionAutoRetranscribeOnStop = value }
            if case .value(let value) = autoRetranscribeDuringRecording { viewModel.sessionAutoRetranscribeDuringRecording = value }
            if case .value(let value) = autoAnalyzeOnComplete { viewModel.sessionAutoAnalyzeOnComplete = value }
            if let validatedModes { viewModel.sessionAutoAnalyzeModes = validatedModes }
            if case .value(let value) = instructions { viewModel.sessionAutoAnalyzeCustomInstructions = value }
            if let validatedTiming { viewModel.sessionAutoAnalyzeTiming = validatedTiming }
        case .setAnalysisConfiguration:
            var validatedModes: Set<AnalysisMode>?
            if payload.keys.contains("modes") {
                guard let modeStrings = payload["modes"] as? [String] else {
                    publishValidationError("invalid_analysis_mode", "One or more analysis modes are unsupported.")
                    return
                }
                let modes = modeStrings.compactMap(AnalysisMode.init(rawValue:))
                guard modes.count == modeStrings.count else {
                    publishValidationError("invalid_analysis_mode", "One or more analysis modes are unsupported.")
                    return
                }
                validatedModes = Set(modes)
            }

            let instructions = optionalString("customInstructions", in: payload)
            let expanded = optionalBool("isExpanded", in: payload)
            guard instructions != .invalid, expanded != .invalid else {
                publishValidationError("invalid_analysis_configuration", "The analysis configuration was malformed.")
                return
            }

            var validatedModelId: String?
            if payload.keys.contains("modelId") {
                guard let modelId = payload["modelId"] as? String else {
                    publishValidationError("invalid_analysis_model", "That analysis model is no longer available.")
                    return
                }
                let availableIds = (viewModel.localAnalysisModels + viewModel.apiAnalysisModels).map(\.id)
                guard availableIds.contains(modelId) else {
                    publishValidationError("invalid_analysis_model", "That analysis model is no longer available.")
                    return
                }
                validatedModelId = modelId
            }

            if let validatedModes { viewModel.selectedAnalysisModes = validatedModes }
            if case .value(let value) = instructions { viewModel.analysisCustomInstructions = value }
            if let validatedModelId { viewModel.selectedAnalysisModelId = validatedModelId }
            if case .value(let value) = expanded { viewModel.isAnalysisSectionExpanded = value }
        case .startAnalysis:
            guard !viewModel.isRecording,
                  viewModel.hasTranscription,
                  !viewModel.isAnalyzing,
                  !viewModel.selectedAnalysisModes.isEmpty,
                  viewModel.selectedAnalysisModelId != nil else {
                publishValidationError("analysis_unavailable", "Analysis cannot start with the current selection.")
                return
            }
            Task { await viewModel.startMeetingAnalysis() }
        case .viewAnalysis:
            guard let filename = payload["filename"] as? String, !filename.isEmpty,
                  viewModel.analysisHistory.contains(where: { $0.filename == filename }),
                  let meetingId = viewModel.selectedMeetingId ?? viewModel.activeAnalysisMeetingId else { return }
            Task { await viewModel.viewAnalysis(meetingId: meetingId, filename: filename) }
        case .deleteAnalysis:
            guard let filename = payload["filename"] as? String, !filename.isEmpty,
                  viewModel.analysisHistory.contains(where: { $0.filename == filename }),
                  let meetingId = viewModel.selectedMeetingId ?? viewModel.activeAnalysisMeetingId else { return }
            Task { await viewModel.deleteAnalysis(meetingId: meetingId, filename: filename) }
        case .retryAnalysisModes:
            guard let filename = payload["filename"] as? String, !filename.isEmpty,
                  let modeStrings = payload["modes"] as? [String], !modeStrings.isEmpty else { return }
            if let currentFilename = bridgePublisher?.currentAnalysisFilename,
               currentFilename != filename {
                publishValidationError("stale_analysis", "That analysis result is no longer active.")
                return
            }
            let modes = modeStrings.compactMap(AnalysisMode.init(rawValue:))
            guard modes.count == modeStrings.count else {
                publishValidationError("invalid_retry_modes", "One or more retry modes are unsupported.")
                return
            }
            viewModel.retryFailedAnalysisModes(
                modes,
                customInstructions: bridgePublisher?.currentAnalysisCustomInstructions
            )
        case .copyText:
            guard let text = payload["text"] as? String else { return }
            let rich = payload["rich"] as? Bool ?? false
            NSPasteboard.general.clearContents()
            if rich {
                let attributed = MarkdownUtils.markdownToAttributedString(text)
                NSPasteboard.general.setString(attributed.string, forType: .string)
            } else {
                NSPasteboard.general.setString(text, forType: .string)
            }
        case .updateProposal:
            guard let proposalId = payload["proposalId"] as? String else { return }
            if let draft = payload["draftPrompt"] as? String {
                bridgePublisher?.updateProposalDraft(proposalId: proposalId, draft: draft)
            }
            if let editing = payload["isEditingDraft"] as? Bool {
                bridgePublisher?.setProposalEditing(proposalId: proposalId, editing: editing)
            }
        case .promoteProposalToTodo:
            guard let proposalId = payload["proposalId"] as? String, !proposalId.isEmpty else { return }
            bridgePublisher?.submitProposal(proposalId: proposalId)
        case .startProposalNow:
            guard let proposalId = payload["proposalId"] as? String, !proposalId.isEmpty else { return }
            bridgePublisher?.startProposalNow(proposalId: proposalId)
        case .openProposalTodo:
            guard let todoId = payload["todoId"] as? String, !todoId.isEmpty else { return }
            _ = AgentTaskOriginNavigator.open(originType: "todo", originId: todoId, originatingWindow: nil)
        case .openProposalAgentTask:
            guard let agentTaskId = payload["agentTaskId"] as? String, !agentTaskId.isEmpty else { return }
            AgentTaskResultPresentationRouter.showExistingAgentTask(agentTaskId: agentTaskId)
        case .promoteAllProposalsToTodos:
            bridgePublisher?.submitAllEligibleProposals()
        case .dismissProposal:
            guard let proposalId = payload["proposalId"] as? String else { return }
            bridgePublisher?.dismissProposal(proposalId: proposalId)
        case .restoreProposal:
            guard let proposalId = payload["proposalId"] as? String else { return }
            bridgePublisher?.restoreProposal(proposalId: proposalId)
        case .exportAnalysis, .reactReady, .closeWindow, .minimizeWindow, .toggleWindowCollapse, .chromeHeight:
            // exportAnalysis's native save-panel side effect and every window
            // chrome intent (including chrome height) are handled by the
            // presentation host before reaching this shared handler; `exportAnalysis` still arrives
            // here once (with `exported: true`) purely so a future analytics
            // hook has one place to observe it, and currently no-ops.
            break
        }
    }

    private func int32Value(_ value: Any?) -> Int32? {
        if let number = value as? Int32 { return number }
        if let number = value as? Int { return Int32(number) }
        if let number = value as? NSNumber { return number.int32Value }
        return nil
    }

    private func publishValidationError(_ code: String, _ message: String) {
        bridgePublisher?.publishValidationError(code: code, message: message)
    }

    private enum OptionalPayloadValue<Value: Equatable>: Equatable {
        case absent
        case value(Value)
        case invalid
    }

    private func optionalString(_ key: String, in payload: [String: Any]) -> OptionalPayloadValue<String> {
        guard payload.keys.contains(key) else { return .absent }
        guard let value = payload[key] as? String else { return .invalid }
        return .value(value)
    }

    private func optionalBool(_ key: String, in payload: [String: Any]) -> OptionalPayloadValue<Bool> {
        guard payload.keys.contains(key) else { return .absent }
        guard let value = payload[key] as? Bool else { return .invalid }
        return .value(value)
    }

    private func meetingHistorySearchFilters(from payload: [String: Any]) -> MeetingHistorySearchFilters? {
        let stringKeys = [
            "queryMode", "name", "nameMode", "purpose", "purposeMode",
            "participants", "participantsMode", "transcript", "transcriptMode",
            "source", "sourceMode", "processing", "analysis",
        ]
        guard let values = requiredStrings(stringKeys, in: payload),
              let queryMode = MeetingSearchTermMode(rawValue: values["queryMode"] ?? ""),
              let nameMode = MeetingSearchTermMode(rawValue: values["nameMode"] ?? ""),
              let purposeMode = MeetingSearchTermMode(rawValue: values["purposeMode"] ?? ""),
              let participantsMode = MeetingSearchTermMode(rawValue: values["participantsMode"] ?? ""),
              let transcriptMode = MeetingSearchTermMode(rawValue: values["transcriptMode"] ?? ""),
              let sourceMode = MeetingSearchTermMode(rawValue: values["sourceMode"] ?? ""),
              let processing = MeetingProcessingFilter(rawValue: values["processing"] ?? ""),
              let analysis = MeetingAnalysisFilter(rawValue: values["analysis"] ?? ""),
              case .value(let startDate) = optionalISODate("startDate", in: payload),
              case .value(let endDate) = optionalISODate("endDate", in: payload),
              startDate.map({ start in endDate.map({ start <= $0 }) ?? true }) ?? true else {
            return nil
        }
        return MeetingHistorySearchFilters(
            queryMode: queryMode,
            name: values["name"] ?? "",
            nameMode: nameMode,
            purpose: values["purpose"] ?? "",
            purposeMode: purposeMode,
            participants: values["participants"] ?? "",
            participantsMode: participantsMode,
            transcript: values["transcript"] ?? "",
            transcriptMode: transcriptMode,
            source: values["source"] ?? "",
            sourceMode: sourceMode,
            startDate: startDate,
            endDate: endDate,
            processing: processing,
            analysis: analysis
        )
    }

    private func requiredStrings(_ keys: [String], in payload: [String: Any]) -> [String: String]? {
        var values: [String: String] = [:]
        for key in keys {
            guard let value = payload[key] as? String else { return nil }
            values[key] = value
        }
        return values
    }

    private func optionalISODate(_ key: String, in payload: [String: Any]) -> OptionalPayloadValue<String?> {
        guard payload.keys.contains(key) else { return .value(nil) }
        if payload[key] is NSNull { return .value(nil) }
        guard let value = payload[key] as? String else { return .invalid }
        guard value.isEmpty || Self.isoDateFormatter.date(from: value) != nil else { return .invalid }
        return .value(value.isEmpty ? nil : value)
    }

    private static let isoDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        return formatter
    }()
}
