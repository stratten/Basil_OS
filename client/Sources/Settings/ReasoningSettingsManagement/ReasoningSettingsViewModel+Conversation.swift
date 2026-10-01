import Foundation

extension ReasoningSettingsViewModel {
    func loadConversationSettings() async {
        do {
            let settings = try await APIClient.shared.getConversationWidgetSettings()
            conversationDefaultConversationOnly = settings.defaultConversationOnly ?? false
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load the Conversation only default: \(error)", context: "ReasoningSettings")
            #endif
        }
    }

    func updateConversationDefaultConversationOnly(_ enabled: Bool) async {
        do {
            try await APIClient.shared.updateConversationDefaultConversationOnly(enabled)
            conversationDefaultConversationOnly = enabled
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update the Conversation only default: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update the Conversation only default: \(error.localizedDescription)"
        }
    }
}
