import AppKit
import Foundation

extension HotkeyService {
    /// Gate 4 of `handleAgentTaskHotkey()`: open a fresh capture input.
    ///
    /// When this Mac can take the capture, the capture widget is shown right here, before the backend round trip. The backend still receives the wake-word callback, so screenshot context, wake-word pausing, and lifecycle tracking are unchanged. The widget is armed to treat the backend's later `agent_task_capture_started` event as an acknowledgment rather than a second press.
    ///
    /// When another recording owner blocks the capture, nothing is shown early and the legacy request-only path runs, so the backend makes the decision exactly as before.
    @MainActor
    func beginDefaultAgentTaskCapture() async {
        AgentTaskCaptureLatencyTrace.shared.begin()

        guard WebSocketService.shared.checkCanAcceptAgentTask(),
              let coordinator = (NSApplication.shared.delegate as? AppDelegate)?.statusBarManager?.windowCoordinator else {
            await startAgentTaskCapture()
            return
        }

        coordinator.showAgentTaskCaptureWidget(awaitingBackendAcknowledgment: true)
        AgentTaskCaptureLatencyTrace.shared.mark(.widgetRequested)

        let backendAccepted = await startAgentTaskCapture()
        AgentTaskCaptureLatencyTrace.shared.mark(.backendResponded)

        if !backendAccepted {
            AgentTaskCaptureInputWindowController.activeController?.dismissAfterBackendRejection()
        }
    }

    /// Reads the `accepted` flag of the wake-word callback response.
    ///
    /// A backend that predates the flag, or a body that is not a JSON object, counts as accepted so the widget the hotkey already showed is kept.
    nonisolated static func backendAcceptedWakeWord(_ responseData: Data) -> Bool {
        guard let object = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any],
              let accepted = object["accepted"] as? Bool else {
            return true
        }
        return accepted
    }
}
