import Foundation

enum ReasoningDefaultsSettingsPayloadBuilder {
    static func makeSettingsPayload(
        localModels: [ReasoningModelInfo],
        apiModels: [ReasoningModelInfo],
        customModels: [ReasoningModelInfo],
        selectedModelId: String,
        useApiModels: Bool,
        closeAssistantSessionOnInsert: Bool,
        assistantOutputPasteMode: AssistantOutputPasteMode,
        useRegionSelection: Bool,
        modelUnloadDelaySeconds: Int = 300,
        keepModelLoadedWhileWindowOpen: Bool = true,
        agentTaskDefaultModality: AgentTaskInputModality,
        agentTaskAutoReopenOnCompletion: Bool,
        agentTaskChainExpansion: String = AppearanceSettings.defaultAgentTaskChainExpansion,
        agentTaskPushToTalk: Bool,
        agentTaskPushToTalkThreshold: Int,
        assistantSessionDefaultModality: AssistantSessionInputMode,
        assistantSessionPushToTalk: Bool,
        assistantSessionPushToTalkThreshold: Int,
        conversationDefaultConversationOnly: Bool = false
    ) -> [String: Any] {
        [
            "localModels": localModels.map(makeModelInfoPayload),
            "apiModels": apiModels.map(makeModelInfoPayload),
            "customModels": customModels.map(makeModelInfoPayload),
            "selectedModelId": selectedModelId,
            "useApiModels": useApiModels,
            "closeAssistantSessionOnInsert": closeAssistantSessionOnInsert,
            "assistantOutputPasteMode": assistantOutputPasteMode.rawValue,
            "useRegionSelection": useRegionSelection,
            "modelUnloadDelaySeconds": modelUnloadDelaySeconds,
            "keepModelLoadedWhileWindowOpen": keepModelLoadedWhileWindowOpen,
            "agentTaskDefaultModality": agentTaskDefaultModality.rawValue,
            "agentTaskAutoReopenOnCompletion": agentTaskAutoReopenOnCompletion,
            "agentTaskChainExpansion": agentTaskChainExpansion,
            "agentTaskPushToTalk": agentTaskPushToTalk,
            "agentTaskPushToTalkThreshold": agentTaskPushToTalkThreshold,
            "assistantSessionDefaultModality": assistantSessionDefaultModality.rawValue,
            "assistantSessionPushToTalk": assistantSessionPushToTalk,
            "assistantSessionPushToTalkThreshold": assistantSessionPushToTalkThreshold,
            "conversationDefaultConversationOnly": conversationDefaultConversationOnly,
        ]
    }

    @MainActor
    static func makeSettingsPayload(viewModel: ReasoningSettingsViewModel) -> [String: Any] {
        makeSettingsPayload(
            localModels: viewModel.localModels,
            apiModels: viewModel.apiModels,
            customModels: viewModel.customModels,
            selectedModelId: viewModel.selectedModelId,
            useApiModels: viewModel.useApiModels,
            closeAssistantSessionOnInsert: viewModel.closeAssistantSessionOnInsert,
            assistantOutputPasteMode: viewModel.assistantOutputPasteMode,
            useRegionSelection: viewModel.useRegionSelection,
            modelUnloadDelaySeconds: viewModel.modelUnloadDelaySeconds,
            keepModelLoadedWhileWindowOpen: viewModel.keepModelLoadedWhileWindowOpen,
            agentTaskDefaultModality: viewModel.agentTaskDefaultModality,
            agentTaskAutoReopenOnCompletion: viewModel.agentTaskAutoReopenOnCompletion,
            agentTaskChainExpansion: viewModel.agentTaskChainExpansion,
            agentTaskPushToTalk: viewModel.agentTaskPushToTalk,
            agentTaskPushToTalkThreshold: viewModel.agentTaskPushToTalkThreshold,
            assistantSessionDefaultModality: viewModel.assistantSessionDefaultModality,
            assistantSessionPushToTalk: viewModel.assistantSessionPushToTalk,
            assistantSessionPushToTalkThreshold: viewModel.assistantSessionPushToTalkThreshold,
            conversationDefaultConversationOnly: viewModel.conversationDefaultConversationOnly
        )
    }

    static func makeModelInfoPayload(_ model: ReasoningModelInfo) -> [String: Any] {
        [
            "id": model.id,
            "name": model.name,
            "displayName": model.displayName,
            "provider": model.provider,
            "isApiModel": model.isApiModel,
        ]
    }
}
