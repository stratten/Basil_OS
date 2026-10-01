import SwiftUI
import AVFoundation
import ApplicationServices
import CoreGraphics
@preconcurrency import WebKit

struct SetupPermissionsStatusSnapshot {
    let microphone: String
    let accessibility: String
    let inputMonitoring: String
    let screenRecording: String
    let appleEvents: String

    var allRequiredPermissionsGranted: Bool {
        microphone == "granted"
            && accessibility == "granted"
            && inputMonitoring == "granted"
            && screenRecording == "granted"
            && appleEvents == "granted"
    }

    var bridgePayload: [String: String] {
        [
            "microphone": microphone,
            "accessibility": accessibility,
            "input_monitoring": inputMonitoring,
            "screen_recording": screenRecording,
            "apple_events": appleEvents
        ]
    }
}

@MainActor
enum SetupPermissionsStatusEvaluator {
    static func currentStatus() async -> SetupPermissionsStatusSnapshot {
        SetupPermissionsStatusSnapshot(
            microphone: microphonePermissionStatus(),
            accessibility: accessibilityPermissionStatus(),
            inputMonitoring: inputMonitoringPermissionStatus(),
            screenRecording: await screenRecordingPermissionStatus(),
            appleEvents: appleEventsPermissionStatus()
        )
    }

    private static func microphonePermissionStatus() -> String {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return "granted"
        case .denied, .restricted:
            return "denied"
        case .notDetermined:
            return "not_determined"
        @unknown default:
            return "unknown"
        }
    }

    private static func accessibilityPermissionStatus() -> String {
        AXIsProcessTrusted() ? "granted" : "denied"
    }

    private static func inputMonitoringPermissionStatus() -> String {
        guard let testMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown], handler: { _ in }) else {
            return "denied"
        }
        NSEvent.removeMonitor(testMonitor)
        return "granted"
    }

    private static func screenRecordingPermissionStatus() async -> String {
        CGPreflightScreenCaptureAccess() ? "granted" : "denied"
    }

    private static func appleEventsPermissionStatus() -> String {
        let script = "tell application \"System Events\" to return true"
        var error: NSDictionary?
        guard let appleScript = NSAppleScript(source: script) else {
            return "unknown"
        }

        let result = appleScript.executeAndReturnError(&error)
        if let nsError = error as? [String: AnyObject],
           let errorNumber = nsError[NSAppleScript.errorNumber] as? Int,
           errorNumber == -1743 {
            return "denied"
        }

        if error == nil && result.booleanValue {
            return "granted"
        }

        return "not_determined"
    }
}

struct SetupPermissionsWebView: NSViewRepresentable {
    var isReturningUserCheck: Bool = false
    var onRestartRequested: (() -> Void)?
    var onContinueRequested: (() -> Void)?
    var onCloseRequested: (() -> Void)?
    var onMinimizeRequested: (() -> Void)?
    var onCollapseRequested: (() -> Void)?
    var onExpandRequested: (() -> Void)?
    var onCoordinatorReady: ((Coordinator) -> Void)?
    var onLoadFailed: (() -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(
            onRestartRequested: onRestartRequested,
            onContinueRequested: onContinueRequested,
            onCloseRequested: onCloseRequested,
            onMinimizeRequested: onMinimizeRequested,
            onCollapseRequested: onCollapseRequested,
            onExpandRequested: onExpandRequested,
            onLoadFailed: onLoadFailed
        )
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        let config: [String: Any] = [
            "apiBaseUrl": APIClient.shared.baseURL,
            "theme": SetupAssistantThemePayload.theme(),
            "fonts": SetupAssistantThemePayload.fonts(),
            "isReturningUserCheck": isReturningUserCheck,
        ]
        let configData = try? JSONSerialization.data(withJSONObject: config, options: [])
        let configJSON = configData.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        let configScript = WKUserScript(
            source: "window.basilSetupAssistantConfig = \(configJSON);",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        configuration.userContentController.addUserScript(configScript)

        let consoleScript = WKUserScript(
            source: """
                (function() {
                    var originalLog = console.log;
                    var originalError = console.error;
                    var originalWarn = console.warn;
                    console.log = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'log', message: Array.from(arguments).join(' ')});
                        originalLog.apply(console, arguments);
                    };
                    console.error = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'error', message: Array.from(arguments).join(' ')});
                        originalError.apply(console, arguments);
                    };
                    console.warn = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'warn', message: Array.from(arguments).join(' ')});
                        originalWarn.apply(console, arguments);
                    };
                })();
                """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: false
        )
        configuration.userContentController.addUserScript(consoleScript)
        configuration.userContentController.add(context.coordinator, name: "setupAssistant")
        configuration.userContentController.add(context.coordinator, name: "jsLog")

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.setValue(false, forKey: "drawsBackground")

        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }

        SetupWindowDragAreaInstaller.install(in: webView)
        context.coordinator.loadContent(in: webView)
        onCoordinatorReady?(context.coordinator)
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler, AppearanceRefreshable {
        private var onRestartRequested: (() -> Void)?
        private var onContinueRequested: (() -> Void)?
        private var onCloseRequested: (() -> Void)?
        private var onMinimizeRequested: (() -> Void)?
        private var onCollapseRequested: (() -> Void)?
        private var onExpandRequested: (() -> Void)?
        private var onLoadFailed: (() -> Void)?
        private weak var webView: WKWebView?

        init(
            onRestartRequested: (() -> Void)?,
            onContinueRequested: (() -> Void)?,
            onCloseRequested: (() -> Void)?,
            onMinimizeRequested: (() -> Void)?,
            onCollapseRequested: (() -> Void)?,
            onExpandRequested: (() -> Void)?,
            onLoadFailed: (() -> Void)? = nil
        ) {
            self.onRestartRequested = onRestartRequested
            self.onContinueRequested = onContinueRequested
            self.onCloseRequested = onCloseRequested
            self.onMinimizeRequested = onMinimizeRequested
            self.onCollapseRequested = onCollapseRequested
            self.onExpandRequested = onExpandRequested
            self.onLoadFailed = onLoadFailed
        }

        func loadContent(in webView: WKWebView) {
            self.webView = webView

            guard let resourceURL = Bundle.main.resourceURL else {
                DevLogger.shared.error("[SetupPermissionsWebView] Could not get resource URL", context: "SetupAssistant")
                onLoadFailed?()
                return
            }

            let webAssetsFolder = resourceURL.appendingPathComponent("SetupAssistantWebAssets")
            let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/setup-permissions.html")

            if FileManager.default.fileExists(atPath: htmlURL.path) {
                webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
            } else {
                DevLogger.shared.error("[SetupPermissionsWebView] HTML file not found at \(htmlURL.path)", context: "SetupAssistant")
                onLoadFailed?()
            }
        }

        func refreshAppearance() {
            let detail: [String: Any] = [
                "theme": SetupAssistantThemePayload.theme(),
                "fonts": SetupAssistantThemePayload.fonts(),
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: detail),
                  let json = String(data: data, encoding: .utf8) else {
                return
            }
            webView?.evaluateJavaScript(
                "window.basilSetupAssistantConfig = { ...(window.basilSetupAssistantConfig || {}), theme: \(json).theme, fonts: \(json).fonts }; window.dispatchEvent(new CustomEvent('setupAssistantThemeChanged', { detail: \(json) }));"
            )
        }

        func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            if message.name == "jsLog" {
                handleLogMessage(message.body)
                return
            }

            guard message.name == "setupAssistant",
                  let body = message.body as? [String: Any],
                  let name = body["name"] as? String else {
                return
            }

            handleSetupPermissionsMessage(name: name, payload: body["payload"] as? [String: Any])
        }

        private func handleLogMessage(_ body: Any) {
            guard let log = body as? [String: String] else { return }
            let level = log["level"] ?? "log"
            let message = log["message"] ?? ""
            DevLogger.shared.info("[SetupPermissions JS \(level)] \(message)", context: "SetupAssistant")
        }

        private func handleSetupPermissionsMessage(name: String, payload: [String: Any]?) {
            switch name {
            case "requestPermissionStatus":
                dispatchPermissionStatus()
            case "requestPermission":
                requestPermission(payload: payload)
            case "openSystemSettings":
                openSystemSettings(payload: payload)
            case "restartApplication":
                onRestartRequested?()
            case "continueSetupAssistant":
                onContinueRequested?()
            case "closeSetupAssistant":
                onCloseRequested?()
            case "minimizeSetupAssistant":
                onMinimizeRequested?()
            case "collapseSetupAssistant":
                onCollapseRequested?()
            case "expandSetupAssistant":
                onExpandRequested?()
            default:
                DevLogger.shared.warning("[SetupPermissionsWebView] Unknown bridge action: \(name)", context: "SetupAssistant")
            }
        }

        private func dispatchPermissionStatus() {
            Task { @MainActor [weak self] in
                let snapshot = await SetupPermissionsStatusEvaluator.currentStatus()
                self?.dispatchPermissionStatus(snapshot: snapshot)
            }
        }

        @MainActor
        private func dispatchPermissionStatus(snapshot: SetupPermissionsStatusSnapshot) {
            let eventPayload: [String: Any] = ["permissions": snapshot.bridgePayload]

            guard
                let data = try? JSONSerialization.data(withJSONObject: eventPayload),
                let json = String(data: data, encoding: .utf8)
            else {
                DevLogger.shared.error("[SetupPermissionsWebView] Failed to serialize permission status", context: "SetupAssistant")
                return
            }

            webView?.evaluateJavaScript(
                "window.dispatchEvent(new CustomEvent('setupAssistantPermissionStatus', { detail: \(json) }));"
            ) { _, error in
                if let error {
                    DevLogger.shared.error("[SetupPermissionsWebView] Failed to dispatch permission status: \(error)", context: "SetupAssistant")
                }
            }
        }

        private func requestPermission(payload: [String: Any]?) {
            guard let kind = payload?["kind"] as? String else {
                DevLogger.shared.warning("[SetupPermissionsWebView] Missing permission request kind", context: "SetupAssistant")
                return
            }

            switch kind {
            case "microphone":
                AVCaptureDevice.requestAccess(for: .audio) { [weak self] _ in
                    DispatchQueue.main.async {
                        self?.dispatchPermissionStatus()
                    }
                }
            case "accessibility":
                let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
                _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                    self?.dispatchPermissionStatus()
                }
            case "input_monitoring":
                openSystemSettings(payload: ["kind": "input_monitoring"])
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                    self?.dispatchPermissionStatus()
                }
            case "screen_recording":
                _ = CGRequestScreenCaptureAccess()
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                    self?.dispatchPermissionStatus()
                }
            case "apple_events":
                var error: NSDictionary?
                if let appleScript = NSAppleScript(source: "tell application \"System Events\" to launch") {
                    appleScript.executeAndReturnError(&error)
                }
                if let error {
                    DevLogger.shared.warning("[SetupPermissionsWebView] Apple Events permission request returned: \(error)", context: "SetupAssistant")
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                    self?.dispatchPermissionStatus()
                }
            default:
                DevLogger.shared.warning("[SetupPermissionsWebView] Unknown permission request kind: \(kind)", context: "SetupAssistant")
            }
        }

        private func openSystemSettings(payload: [String: Any]?) {
            let kind = payload?["kind"] as? String
            let path = systemSettingsPath(for: kind)
            let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(path)")!
            NSWorkspace.shared.open(url)
            DevLogger.shared.info("[SetupPermissionsWebView] Opened System Settings for \(kind ?? "privacy")", context: "SetupAssistant")
        }

        private func systemSettingsPath(for kind: String?) -> String {
            switch kind {
            case "microphone":
                return "Privacy_Microphone"
            case "accessibility":
                return "Privacy_Accessibility"
            case "input_monitoring":
                return "Privacy_ListenEvent"
            case "apple_events":
                return "Privacy_Automation"
            case "screen_recording":
                return "Privacy_ScreenCapture"
            default:
                return "Privacy"
            }
        }
    }
}
