import Foundation
@preconcurrency import WebKit

struct HotkeySettingsBindingPayload {
    let key: String
    let enabled: Bool
    let modifiers: [String]
    let isDoublePress: Bool
    let doublePressKey: String?

    init?(raw: [String: Any]) {
        guard
            let key = raw["key"] as? String,
            let enabled = (raw["enabled"] as? NSNumber)?.boolValue,
            let modifiers = raw["modifiers"] as? [String]
        else { return nil }
        self.key = key
        self.enabled = enabled
        self.modifiers = modifiers
        self.isDoublePress = (raw["isDoublePress"] as? NSNumber)?.boolValue ?? false
        self.doublePressKey = raw["doublePressKey"] as? String
    }

    func toHotkeyBinding(preservingDescription description: String) -> HotkeyBinding {
        HotkeyBinding(
            key: key,
            enabled: enabled,
            modifiers: modifiers,
            hotkeyDescription: description,
            isDoublePress: isDoublePress,
            doublePressKey: doublePressKey
        )
    }
}

@MainActor
final class HotkeySettingsWebView: NSObject {
    private let webView: WKWebView

    var onReady: (() -> Void)?
    var onStartCapture: ((String) -> Void)?
    var onCancelCapture: ((String) -> Void)?
    var onSaveBinding: ((String, String, HotkeySettingsBindingPayload) -> Void)?
    var onToggleEnableMonitoring: ((String, Bool) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        webView.configuration.userContentController.add(
            HotkeySettingsWeakScriptMessageHandler(self),
            name: "basilHotkeySettingsBridge"
        )
    }

    func callJS(_ function: String, args: Any...) {
        guard args.count == 1 else { return }
        webView.callAsyncJavaScript(
            "\(function)(event)",
            arguments: ["event": args[0]],
            in: nil,
            in: .page
        ) { result in
            if case .failure(let error) = result {
                #if DEBUG
                DevLogger.shared.error("[HOTKEY_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "HotkeySettingsWebView")
                #endif
            }
        }
    }

    func markReadyFromReact() {
        onReady?()
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilHotkeySettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilHotkeySettingsBridge",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else {
            return
        }

        switch type {
        case "reactReady":
            guard (body["protocolVersion"] as? NSNumber)?.intValue == 1 else {
                onMalformedIntent?("reactReady")
                return
            }
            markReadyFromReact()
        case "startCapture":
            guard let id = body["id"] as? String else {
                onMalformedIntent?("startCapture")
                return
            }
            onStartCapture?(id)
        case "cancelCapture":
            guard let id = body["id"] as? String else {
                onMalformedIntent?("cancelCapture")
                return
            }
            onCancelCapture?(id)
        case "saveBinding":
            guard let requestId = body["requestId"] as? String,
                  let id = body["id"] as? String,
                  let rawBinding = body["binding"] as? [String: Any],
                  let payload = HotkeySettingsBindingPayload(raw: rawBinding) else {
                onMalformedIntent?("saveBinding")
                return
            }
            onSaveBinding?(requestId, id, payload)
        case "toggleEnableMonitoring":
            guard let requestId = body["requestId"] as? String,
                  let enabled = (body["enabled"] as? NSNumber)?.boolValue else {
                onMalformedIntent?("toggleEnableMonitoring")
                return
            }
            onToggleEnableMonitoring?(requestId, enabled)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class HotkeySettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: HotkeySettingsWebView?

    init(_ target: HotkeySettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
