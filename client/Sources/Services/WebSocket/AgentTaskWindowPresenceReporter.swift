import Combine
import Foundation

/// Tells the backend which agent-task windows are open.
///
/// While at least one is open, and "Keep model loaded while a window is open" is
/// on, the backend does not idle-unload the local reasoning model, because the
/// user may continue that task. The backend ties each report to this WebSocket
/// connection, so it forgets them when the connection drops. This reporter
/// therefore announces every open window again each time the socket reconnects.
@MainActor
final class AgentTaskWindowPresenceReporter {
    static let shared = AgentTaskWindowPresenceReporter()

    /// Open window id -> the agent task it shows (empty when not known yet).
    private var openWindows: [String: String] = [:]
    private var cancellable: AnyCancellable?

    private init() {
        cancellable = WebSocketService.shared.eventSubject
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                if case .connectionStateChanged(true) = event {
                    self?.announceAllOpenWindows()
                }
            }
    }

    /// Call when a window that can continue an agent task appears. A minimized
    /// window still counts as open.
    func windowOpened(windowId: String, agentTaskId: String? = nil) {
        openWindows[windowId] = agentTaskId ?? ""
        send(windowId: windowId, agentTaskId: agentTaskId ?? "", present: true)
    }

    /// Call when the window is closed for good.
    func windowClosed(windowId: String) {
        guard openWindows.removeValue(forKey: windowId) != nil else { return }
        send(windowId: windowId, agentTaskId: "", present: false)
    }

    private func announceAllOpenWindows() {
        for (windowId, agentTaskId) in openWindows {
            send(windowId: windowId, agentTaskId: agentTaskId, present: true)
        }
    }

    private func send(windowId: String, agentTaskId: String, present: Bool) {
        let webSocketService = WebSocketService.shared
        // Not connected: nothing to tell. The reconnect announces open windows.
        guard webSocketService.isConnected else { return }
        let message: [String: Any] = [
            "agent_task_action": "window_presence",
            "window_id": windowId,
            "agent_task_id": agentTaskId,
            "present": present
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: message),
              let json = String(data: data, encoding: .utf8) else { return }
        webSocketService.sendMessage(json)
    }
}
