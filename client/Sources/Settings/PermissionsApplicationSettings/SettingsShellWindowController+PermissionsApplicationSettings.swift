import AppKit
import AVFoundation
import ApplicationServices
import Foundation

extension SettingsShellWindowController {
    func wirePermissionsApplicationWebView(_ webView: ReactPermissionsApplicationWebView) {
        webView.onReady = { [weak self] in
            Task { @MainActor in await self?.sendPermissionsApplicationInit() }
        }
        webView.onRequestPermissionStatus = { [weak self] requestId in
            Task { @MainActor in await self?.refreshPermissionsApplicationSnapshot(requestId: requestId) }
        }
        webView.onRequestPermission = { [weak self] requestId, kind in
            self?.performPermissionsApplicationRequest(requestId: requestId, kind: kind)
        }
        webView.onOpenSystemSettings = { [weak self] requestId, kind in
            self?.performPermissionsApplicationOpenSystemSettings(requestId: requestId, kind: kind)
        }
        webView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[PERMISSIONS_APPLICATION] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func sendPermissionsApplicationInit() async {
        guard let webView = permissionsApplicationWebView else { return }
        let snapshot = await SetupPermissionsStatusEvaluator.currentStatus()
        webView.sendInit(snapshot: snapshot)
    }

    private func refreshPermissionsApplicationSnapshot(requestId: String) async {
        guard let webView = permissionsApplicationWebView else { return }
        let snapshot = await SetupPermissionsStatusEvaluator.currentStatus()
        webView.sendSnapshot(snapshot: snapshot)
        webView.sendIntentResult(requestId: requestId, status: "success", message: nil)
    }

    private func performPermissionsApplicationRequest(requestId: String, kind: String) {
        switch kind {
        case "microphone":
            AVCaptureDevice.requestAccess(for: .audio) { [weak self] _ in
                DispatchQueue.main.async {
                    Task { @MainActor in await self?.refreshPermissionsApplicationSnapshot(requestId: requestId) }
                }
            }
        case "accessibility":
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
            _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
            Task { @MainActor [weak self] in
                await self?.refreshPermissionsApplicationSnapshot(requestId: requestId)
            }
        case "input_monitoring":
            performPermissionsApplicationOpenSystemSettings(requestId: nil, kind: "input_monitoring")
            Task { @MainActor [weak self] in
                await self?.refreshPermissionsApplicationSnapshot(requestId: requestId)
            }
        case "screen_recording":
            _ = CGRequestScreenCaptureAccess()
            Task { @MainActor [weak self] in
                await self?.refreshPermissionsApplicationSnapshot(requestId: requestId)
            }
        case "apple_events":
            var error: NSDictionary?
            if let appleScript = NSAppleScript(source: "tell application \"System Events\" to launch") {
                appleScript.executeAndReturnError(&error)
            }
            Task { @MainActor [weak self] in
                await self?.refreshPermissionsApplicationSnapshot(requestId: requestId)
            }
        default:
            guard let webView = permissionsApplicationWebView else { return }
            webView.sendIntentResult(requestId: requestId, status: "error", message: "Unrecognized permission kind.")
        }
    }

    private func performPermissionsApplicationOpenSystemSettings(requestId: String?, kind: String) {
        guard let path = Self.permissionsApplicationSystemSettingsPath(for: kind),
              let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(path)") else {
            if let requestId, let webView = permissionsApplicationWebView {
                webView.sendIntentResult(requestId: requestId, status: "error", message: "Unrecognized permission kind.")
            }
            return
        }
        guard NSWorkspace.shared.open(url) else {
            if let requestId, let webView = permissionsApplicationWebView {
                webView.sendIntentResult(requestId: requestId, status: "error", message: "Unable to open System Settings.")
            }
            return
        }
        if let requestId {
            Task { @MainActor [weak self] in
                await self?.refreshPermissionsApplicationSnapshot(requestId: requestId)
            }
        }
    }

    private static func permissionsApplicationSystemSettingsPath(for kind: String) -> String? {
        switch kind {
        case "microphone": return "Privacy_Microphone"
        case "accessibility": return "Privacy_Accessibility"
        case "input_monitoring": return "Privacy_ListenEvent"
        case "apple_events": return "Privacy_Automation"
        case "screen_recording": return "Privacy_ScreenCapture"
        default: return nil
        }
    }
}
