import Foundation

/// Observable backing store for the Setup Assistant "pending" reminder surface.
///
/// When the user picks "Skip setup for now" inside the bespoke Setup Assistant the
/// backend persists ``pending_setup_assistant=true`` and ``reminder_dismissed=false``
/// in ``~/.config/basil/setup_assistant_state.json``. Settings UI surfaces a Resume
/// card while pending is true; the launch-time menubar toast surfaces while pending
/// is true and reminderDismissed is false. Picking "Done with setup" (or "Don't
/// remind me" on the toast) clears the surfaces via the dedicated endpoints.
@MainActor
final class SetupAssistantPendingStateModel: ObservableObject {
    @Published private(set) var pendingSetupAssistant: Bool = false
    @Published private(set) var reminderDismissed: Bool = false
    @Published private(set) var setupCompleted: Bool = false
    @Published private(set) var isLoading: Bool = false
    @Published private(set) var lastLoadError: String? = nil

    private struct StateResponse: Decodable {
        struct State: Decodable {
            let pending_setup_assistant: Bool?
            let reminder_dismissed: Bool?
            let completed: Bool?
        }
        let state: State
    }

    func loadFromBackend() async {
        isLoading = true
        lastLoadError = nil
        defer { isLoading = false }

        guard let url = URL(string: "\(APIClient.shared.baseURL)/setup-assistant/state") else {
            lastLoadError = "Invalid setup-assistant state URL."
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 4.0

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  (200...299).contains(httpResponse.statusCode) else {
                lastLoadError = "Setup-assistant state request failed."
                return
            }
            let decoded = try JSONDecoder().decode(StateResponse.self, from: data)
            pendingSetupAssistant = decoded.state.pending_setup_assistant ?? false
            reminderDismissed = decoded.state.reminder_dismissed ?? false
            setupCompleted = decoded.state.completed ?? false
        } catch {
            lastLoadError = error.localizedDescription
        }
    }

    /// Suppress the launch-time toast without clearing the pending flag (the Resume
    /// card in Settings remains visible until Done is reached or setup is resumed
    /// and completed).
    func dismissReminder() async {
        guard let url = URL(string: "\(APIClient.shared.baseURL)/setup-assistant/state/dismiss-reminder") else {
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = "{}".data(using: .utf8)
        request.timeoutInterval = 4.0

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  (200...299).contains(httpResponse.statusCode) else {
                return
            }
            reminderDismissed = true
        } catch {
            // Non-fatal: the user can ask us to dismiss again next launch.
        }
    }

    var shouldShowSettingsResumeCard: Bool { pendingSetupAssistant }

    /// A skip always records `completed=false`, so a pending resume never reads as complete.
    var hasCompletedSetupAssistant: Bool { setupCompleted && !pendingSetupAssistant }

    var shouldShowLaunchResumeToast: Bool { pendingSetupAssistant && !reminderDismissed }
}
