import Foundation

extension SettingsShellWindowController {
    func wireReasoningDefaultsSettingsWebView(_ webView: ReactReasoningDefaultsSettingsWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadReasoningDefaultsSettingsAndSendInit() }
        }
        webView.onRequestUpdateSelectedModel = { [weak self] requestId, modelId in
            guard let self, self.isReasoningDefaultsModelAvailable(modelId) else {
                self?.rejectReasoningDefaultsRequest(requestId: requestId, message: "That reasoning model is no longer available.")
                return
            }
            self.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateSelectedModel(modelId) }, isSuccessful: { $0.selectedModelId == modelId }, failureMessage: "Failed to update the default reasoning model.")
        }
        webView.onRequestUpdateCloseAssistantSessionOnInsert = { [weak self] requestId, enabled in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateCloseAssistantSessionOnInsert(enabled) }, isSuccessful: { $0.closeAssistantSessionOnInsert == enabled }, failureMessage: "Failed to update the close-on-insert setting.")
        }
        webView.onRequestUpdateAssistantOutputPasteMode = { [weak self] requestId, mode in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAssistantOutputPasteMode(mode) }, isSuccessful: { $0.assistantOutputPasteMode == mode }, failureMessage: "Failed to update the paste setting.")
        }
        webView.onRequestUpdateUseRegionSelection = { [weak self] requestId, enabled in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateUseRegionSelection(enabled) }, isSuccessful: { $0.useRegionSelection == enabled }, failureMessage: "Failed to update the region-selection setting.")
        }
        webView.onRequestUpdateAgentTaskDefaultModality = { [weak self] requestId, modality in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAgentTaskDefaultModality(modality) }, isSuccessful: { $0.agentTaskDefaultModality == modality }, failureMessage: "Failed to update the AgentTask default input mode.")
        }
        webView.onRequestUpdateAgentTaskAutoReopenOnCompletion = { [weak self] requestId, enabled in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAgentTaskAutoReopenOnCompletion(enabled) }, isSuccessful: { $0.agentTaskAutoReopenOnCompletion == enabled }, failureMessage: "Failed to update the auto-reopen setting.")
        }
        webView.onRequestUpdateAgentTaskPushToTalk = { [weak self] requestId, enabled in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAgentTaskPushToTalk(enabled) }, isSuccessful: { $0.agentTaskPushToTalk == enabled }, failureMessage: "Failed to update AgentTask push-to-talk.")
        }
        webView.onRequestUpdateAgentTaskPushToTalkThreshold = { [weak self] requestId, thresholdMs in
            guard (500...5000).contains(thresholdMs) else {
                self?.rejectReasoningDefaultsRequest(requestId: requestId, message: "Push-to-talk thresholds must be between 500 and 5000 milliseconds.")
                return
            }
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAgentTaskPushToTalkThreshold(thresholdMs) }, isSuccessful: { $0.agentTaskPushToTalkThreshold == thresholdMs }, failureMessage: "Failed to update the AgentTask push-to-talk threshold.")
        }
        webView.onRequestUpdateAssistantSessionDefaultModality = { [weak self] requestId, modality in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAssistantSessionDefaultModality(modality) }, isSuccessful: { $0.assistantSessionDefaultModality == modality }, failureMessage: "Failed to update the AssistantSession default input mode.")
        }
        webView.onRequestUpdateAssistantSessionPushToTalk = { [weak self] requestId, enabled in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAssistantSessionPushToTalk(enabled) }, isSuccessful: { $0.assistantSessionPushToTalk == enabled }, failureMessage: "Failed to update AssistantSession push-to-talk.")
        }
        webView.onRequestUpdateAssistantSessionPushToTalkThreshold = { [weak self] requestId, thresholdMs in
            guard (500...5000).contains(thresholdMs) else {
                self?.rejectReasoningDefaultsRequest(requestId: requestId, message: "Push-to-talk thresholds must be between 500 and 5000 milliseconds.")
                return
            }
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateAssistantSessionPushToTalkThreshold(thresholdMs) }, isSuccessful: { $0.assistantSessionPushToTalkThreshold == thresholdMs }, failureMessage: "Failed to update the AssistantSession push-to-talk threshold.")
        }
        webView.onRequestUpdateConversationDefaultConversationOnly = { [weak self] requestId, enabled in
            self?.performReasoningDefaultsUpdate(requestId: requestId, apply: { await $0.updateConversationDefaultConversationOnly(enabled) }, isSuccessful: { $0.conversationDefaultConversationOnly == enabled }, failureMessage: "Failed to update the Conversation only default.")
        }
    }

    private func loadReasoningDefaultsSettingsAndSendInit() async {
        reasoningDefaultsLoadGeneration += 1
        let generation = reasoningDefaultsLoadGeneration
        #if DEBUG
        DevLogger.shared.debug("[gen \(generation)] onReady -> loadAllSettings() starting", context: "ReasoningDefaults")
        #endif
        await reasoningDefaultsViewModel.loadAllSettings()
        #if DEBUG
        DevLogger.shared.debug("[gen \(generation)] loadAllSettings() finished, agentTaskDefaultModality=\(reasoningDefaultsViewModel.agentTaskDefaultModality.rawValue), currentGeneration=\(reasoningDefaultsLoadGeneration)", context: "ReasoningDefaults")
        #endif
        guard generation == reasoningDefaultsLoadGeneration else {
            #if DEBUG
            DevLogger.shared.debug("[gen \(generation)] DROPPED sendInit: superseded by generation \(reasoningDefaultsLoadGeneration)", context: "ReasoningDefaults")
            #endif
            return
        }
        guard reasoningDefaultsViewModel.error == nil else {
            #if DEBUG
            DevLogger.shared.debug("[gen \(generation)] sendLoadError: \(reasoningDefaultsViewModel.error ?? "unknown")", context: "ReasoningDefaults")
            #endif
            reasoningDefaultsWebView?.sendLoadError(message: reasoningDefaultsViewModel.error ?? "Failed to load reasoning defaults settings.")
            return
        }
        #if DEBUG
        DevLogger.shared.debug("[gen \(generation)] sendInit -> agentTaskDefaultModality=\(reasoningDefaultsViewModel.agentTaskDefaultModality.rawValue)", context: "ReasoningDefaults")
        #endif
        reasoningDefaultsWebView?.sendInit(viewModel: reasoningDefaultsViewModel)
    }

    private func performReasoningDefaultsUpdate(
        requestId: String,
        apply: @escaping (ReasoningSettingsViewModel) async -> Void,
        isSuccessful: @escaping (ReasoningSettingsViewModel) -> Bool,
        failureMessage: String
    ) {
        Task { @MainActor in
            reasoningDefaultsLoadGeneration += 1
            let generation = reasoningDefaultsLoadGeneration
            let vm = reasoningDefaultsViewModel
            vm.error = nil
            #if DEBUG
            DevLogger.shared.debug("[gen \(generation)] requestId=\(requestId) apply() starting", context: "ReasoningDefaults")
            #endif
            await apply(vm)
            let actionError = vm.error
            let succeededBeforeReload = actionError == nil && isSuccessful(vm)
            #if DEBUG
            DevLogger.shared.debug("[gen \(generation)] requestId=\(requestId) apply() finished, succeededBeforeReload=\(succeededBeforeReload), error=\(actionError ?? "none"), agentTaskDefaultModality=\(vm.agentTaskDefaultModality.rawValue)", context: "ReasoningDefaults")
            #endif
            if !succeededBeforeReload {
                await vm.loadAllSettings()
                #if DEBUG
                DevLogger.shared.debug("[gen \(generation)] requestId=\(requestId) recovery loadAllSettings() finished, agentTaskDefaultModality=\(vm.agentTaskDefaultModality.rawValue), currentGeneration=\(reasoningDefaultsLoadGeneration)", context: "ReasoningDefaults")
                #endif
                if generation == reasoningDefaultsLoadGeneration {
                    #if DEBUG
                    DevLogger.shared.debug("[gen \(generation)] requestId=\(requestId) recovery sendSnapshot -> agentTaskDefaultModality=\(vm.agentTaskDefaultModality.rawValue)", context: "ReasoningDefaults")
                    #endif
                    reasoningDefaultsWebView?.sendSnapshot(viewModel: vm)
                } else {
                    #if DEBUG
                    DevLogger.shared.debug("[gen \(generation)] requestId=\(requestId) DROPPED recovery sendSnapshot: superseded by generation \(reasoningDefaultsLoadGeneration)", context: "ReasoningDefaults")
                    #endif
                }
            }
            if succeededBeforeReload {
                #if DEBUG
                DevLogger.shared.debug("[gen \(generation)] requestId=\(requestId) success: preserving optimistic renderer state; no snapshot refresh", context: "ReasoningDefaults")
                #endif
                reasoningDefaultsWebView?.sendIntentResult(requestId: requestId, status: "success", message: nil)
            } else {
                reasoningDefaultsWebView?.sendIntentResult(requestId: requestId, status: "error", message: actionError ?? failureMessage)
            }
        }
    }

    private func isReasoningDefaultsModelAvailable(_ modelId: String) -> Bool {
        reasoningDefaultsViewModel.localModels.contains { $0.id == modelId } ||
            (reasoningDefaultsViewModel.useApiModels &&
                (reasoningDefaultsViewModel.apiModels + reasoningDefaultsViewModel.customModels).contains { $0.id == modelId })
    }

    private func rejectReasoningDefaultsRequest(requestId: String, message: String) {
        reasoningDefaultsWebView?.sendSnapshot(viewModel: reasoningDefaultsViewModel)
        reasoningDefaultsWebView?.sendIntentResult(requestId: requestId, status: "error", message: message)
    }
}
