import Foundation

/// A command the backend may ask this app to run for an agent, after it has been checked against the closed list below.
enum NativeCommandPlan: Equatable {
    case openSettings(tab: String?)
}

/// Why a command was refused. The message goes back to the agent, so it is plain language.
struct NativeCommandFailure: Error, Equatable {
    let message: String
}

/// Reads and checks a `native_command` event. Pure, so it can be tested without a window or a socket.
///
/// The backend validates too (`api/services/app_control/native_commands.py`), and a backend test fails if the verb and tab lists here differ from it. Anything not listed is refused, whatever the backend sent.
enum NativeCommandParser {
    /// The Settings window's top-level tabs. Keep in step with `SettingsShell.tsx`; a backend test checks it.
    static let settingsTabs: Set<String> = [
        // tabs:begin
        "home", "hotkeys", "profile", "memory-intelligence", "writing-examples", "models", "reasoning",
        "transcription", "meetings", "capture", "connections", "permissions", "account", "appearance",
        // tabs:end
    ]

    static func parse(_ json: [String: Any]) -> Result<NativeCommandPlan, NativeCommandFailure> {
        guard let verb = json["verb"] as? String else {
            return .failure(NativeCommandFailure(message: "The command had no verb."))
        }
        let params = json["params"] as? [String: Any] ?? [:]
        switch verb {
        // verbs:begin
        case "open_settings":
            if let unexpected = params.keys.first(where: { $0 != "tab" }) {
                return .failure(NativeCommandFailure(message: "open_settings does not take \(unexpected)."))
            }
            guard let tab = params["tab"] else { return .success(.openSettings(tab: nil)) }
            guard let tabName = tab as? String, settingsTabs.contains(tabName) else {
                return .failure(NativeCommandFailure(message: "That is not a Settings tab."))
            }
            return .success(.openSettings(tab: tabName))
        // verbs:end
        default:
            return .failure(NativeCommandFailure(message: "The app does not run a command named \(verb)."))
        }
    }
}

/// Client responder for agent-requested native commands.
///
/// The backend sends `event_type:"native_command"` with a request id. We run the command, then POST the outcome to `/app-control/native-command/result`, as the audio and calendar probes do. "success" means the app did what was asked, not that the user looked at it.
extension WebSocketService {

    @MainActor
    func handleNativeCommand(_ json: [String: Any]) {
        guard let requestId = json["request_id"] as? String else {
            #if DEBUG
            DevLogger.shared.error("native_command missing request_id", context: "websocket")
            #endif
            return
        }

        switch NativeCommandParser.parse(json) {
        case .failure(let failure):
            Task { @MainActor in
                await Self.sendNativeCommandResult(requestId: requestId, success: false, error: failure.message)
            }
        case .success(let plan):
            switch plan {
            case .openSettings(let tab):
                if let tab {
                    SettingsShellWindowController.shared.navigateToTab(tab)
                } else {
                    SettingsShellWindowController.shared.show()
                }
            }
            Task { @MainActor in
                await Self.sendNativeCommandResult(requestId: requestId, success: true, error: nil)
            }
        }
    }

    @MainActor
    private static func sendNativeCommandResult(requestId: String, success: Bool, error: String?) async {
        guard let url = URL(string: "\(APIClient.shared.baseURL)/app-control/native-command/result") else {
            #if DEBUG
            DevLogger.shared.error("Invalid native command result URL", context: "websocket")
            #endif
            return
        }

        var body: [String: Any] = ["request_id": requestId, "success": success]
        if let error { body["error"] = error }

        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 10.0
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (_, response) = try await URLSession.shared.data(for: request)
            #if DEBUG
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 {
                DevLogger.shared.error("Native command result failed with status: \(httpResponse.statusCode)", context: "websocket")
            }
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to send native command result: \(error)", context: "websocket")
            #endif
        }
    }
}
