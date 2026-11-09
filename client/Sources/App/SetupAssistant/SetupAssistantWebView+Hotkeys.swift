import AppKit
import Foundation

/// Native half of the hotkey conflict check in the Setup Assistant: it reads the person's current hotkeys, proposes free replacements for any that clash, records new keys with the same recorder Settings uses, and saves through the same backend route.
extension SetupAssistantWebView.Coordinator {
    func handleEvaluateHotkeys(requestId: String?) {
        Task { @MainActor in
            do {
                let payload = try await SetupHotkeyWorkflow().evaluate()
                dispatchActionResult(requestId: requestId, status: "executed", message: "Checked your hotkeys.", resultPayload: payload)
            } catch {
                dispatchActionResult(requestId: requestId, status: "failed", message: SetupHotkeyError.message(for: error))
            }
        }
    }

    func handleApplyHotkey(payload: [String: Any]?, requestId: String?) {
        guard let id = payload?["id"] as? String,
              let raw = payload?["binding"] as? [String: Any],
              let requested = HotkeySettingsBindingPayload(raw: raw) else {
            dispatchActionResult(requestId: requestId, status: "failed", message: "I didn't receive the keys to save.")
            return
        }
        let acknowledge = (payload?["acknowledgeConflict"] as? NSNumber)?.boolValue ?? false
        let checkOnly = (payload?["checkOnly"] as? NSNumber)?.boolValue ?? false
        Task { @MainActor in
            do {
                let outcome = try await SetupHotkeyWorkflow().apply(id: id, requested: requested, acknowledgeConflict: acknowledge, checkOnly: checkOnly)
                dispatchActionResult(
                    requestId: requestId,
                    status: "executed",
                    message: outcome.saved ? (checkOnly ? "Those keys are free." : "Saved your hotkey.") : "Those keys clash with something else.",
                    resultPayload: outcome.payload
                )
            } catch {
                dispatchActionResult(requestId: requestId, status: "failed", message: SetupHotkeyError.message(for: error))
            }
        }
    }

    func handleResolveHotkeys(payload: [String: Any]?, requestId: String?) {
        let excluded = Set((payload?["excludeIds"] as? [String]) ?? [])
        Task { @MainActor in
            do {
                let outcome = try await SetupHotkeyWorkflow().resolveConflicts(excluding: excluded)
                dispatchActionResult(
                    requestId: requestId,
                    status: "executed",
                    message: outcome.changes.isEmpty ? "No hotkey needed changing." : "Switched the hotkeys that clashed.",
                    resultPayload: outcome.payload
                )
            } catch {
                dispatchActionResult(requestId: requestId, status: "failed", message: SetupHotkeyError.message(for: error))
            }
        }
    }

    func handleCaptureHotkey(payload: [String: Any]?, requestId: String?) {
        guard let id = payload?["id"] as? String, HotkeyRowCatalog.rows.contains(where: { $0.id == id }) else {
            dispatchActionResult(requestId: requestId, status: "failed", message: SetupHotkeyError.unknownHotkey.errorDescription ?? "")
            return
        }
        Task { @MainActor in
            // A recording the page abandoned is ended first, which answers its request as canceled.
            HotkeyRecordingCapture.shared.cancelCapture()
            let anchor: NSView = webView ?? NSView()
            HotkeyRecordingCapture.shared.startCapture(
                in: anchor,
                onCaptured: { [weak self] displayString in
                    let binding = HotkeyBindingParser.parse(displayString: displayString, enabled: true)
                    self?.dispatchActionResult(
                        requestId: requestId,
                        status: "executed",
                        message: "Captured those keys.",
                        resultPayload: ["captured": true, "binding": SetupHotkeyPayload.binding(binding)]
                    )
                },
                onCanceled: { [weak self] in
                    self?.dispatchActionResult(
                        requestId: requestId,
                        status: "executed",
                        message: "Stopped listening for keys.",
                        resultPayload: ["captured": false]
                    )
                }
            )
        }
    }

    func handleCancelHotkeyCapture() {
        Task { @MainActor in HotkeyRecordingCapture.shared.cancelCapture() }
    }
}
