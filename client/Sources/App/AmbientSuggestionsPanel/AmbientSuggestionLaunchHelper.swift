import AppKit
import Foundation

@MainActor
final class AmbientSuggestionLaunchHelper {
    static let shared = AmbientSuggestionLaunchHelper()

    private init() {}

    func launch(_ suggestion: AmbientSuggestionRecord) {
        switch suggestion.capability {
        case "assistant_session":
            launchAssistantSession(suggestion)
        case "agent_task":
            launchAgentTask(suggestion)
        default:
            DevLogger.shared.warning("Unsupported ambient suggestion capability: \(suggestion.capability)", context: "AmbientSuggestions")
        }
    }

    private func launchAssistantSession(_ suggestion: AmbientSuggestionRecord) {
        AssistantSessionWindowController.showFromSetupAssistant(
            instruction: suggestion.instruction,
            contextText: suggestion.contextText,
            applicationName: suggestion.appName,
            modelId: nil
        )
    }

    private func launchAgentTask(_ suggestion: AmbientSuggestionRecord) {
        let agentTaskId = UUID().uuidString
        let prompt = """
        \(suggestion.instruction)

        Context:
        \(suggestion.contextText)
        """
        AgentTaskResultPresentationRouter.installNewAgent(
            agentTaskId: agentTaskId,
            initialAgentTask: prompt
        )

        Task { @MainActor in
            do {
                _ = try await APIClient.shared.processAgentTask(
                    prompt,
                    agentTaskId: agentTaskId,
                    modelId: nil
                )
            } catch {
                DevLogger.shared.error("Failed to launch ambient Paprika suggestion: \(error)", context: "AmbientSuggestions")
            }
        }
    }
}
