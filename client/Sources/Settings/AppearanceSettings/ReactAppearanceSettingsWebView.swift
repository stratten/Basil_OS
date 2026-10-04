import AppKit
@preconcurrency import WebKit

struct ReactAppearanceSettingsDraftPayload {
    let backgroundColorRed: Double
    let backgroundColorGreen: Double
    let backgroundColorBlue: Double
    let primaryColorRed: Double
    let primaryColorGreen: Double
    let primaryColorBlue: Double
    let secondaryColorRed: Double
    let secondaryColorGreen: Double
    let secondaryColorBlue: Double
    let textColorRed: Double
    let textColorGreen: Double
    let textColorBlue: Double
    let processingColorRed: Double
    let processingColorGreen: Double
    let processingColorBlue: Double
    let processingAccentColorRed: Double
    let processingAccentColorGreen: Double
    let processingAccentColorBlue: Double
    let preferredFont: String
    let surfaceFinish: String

    /// Returns nil if `raw` is missing any required numeric field, any
    /// numeric field is outside 0...1, or `preferredFont` is missing/empty.
    /// Font membership in `AestheticSystem.availableFonts` is checked by the
    /// caller (`SettingsShellWindowController`), not here,
    /// so this initializer stays a pure shape/range validator.
    init?(raw: [String: Any]) {
        func component(_ key: String) -> Double? {
            guard let value = (raw[key] as? NSNumber)?.doubleValue else { return nil }
            guard value >= 0, value <= 1 else { return nil }
            return value
        }
        guard
            let backgroundColorRed = component("backgroundColorRed"),
            let backgroundColorGreen = component("backgroundColorGreen"),
            let backgroundColorBlue = component("backgroundColorBlue"),
            let primaryColorRed = component("primaryColorRed"),
            let primaryColorGreen = component("primaryColorGreen"),
            let primaryColorBlue = component("primaryColorBlue"),
            let secondaryColorRed = component("secondaryColorRed"),
            let secondaryColorGreen = component("secondaryColorGreen"),
            let secondaryColorBlue = component("secondaryColorBlue"),
            let textColorRed = component("textColorRed"),
            let textColorGreen = component("textColorGreen"),
            let textColorBlue = component("textColorBlue"),
            let processingColorRed = component("processingColorRed"),
            let processingColorGreen = component("processingColorGreen"),
            let processingColorBlue = component("processingColorBlue"),
            let processingAccentColorRed = component("processingAccentColorRed"),
            let processingAccentColorGreen = component("processingAccentColorGreen"),
            let processingAccentColorBlue = component("processingAccentColorBlue"),
            let preferredFont = raw["preferredFont"] as? String,
            !preferredFont.isEmpty
        else { return nil }
        let surfaceFinish = raw["surfaceFinish"] as? String ?? AppearanceSettings.defaultSurfaceFinish
        guard AppearanceSettings.supportedSurfaceFinishes.contains(surfaceFinish) else { return nil }
        self.backgroundColorRed = backgroundColorRed
        self.backgroundColorGreen = backgroundColorGreen
        self.backgroundColorBlue = backgroundColorBlue
        self.primaryColorRed = primaryColorRed
        self.primaryColorGreen = primaryColorGreen
        self.primaryColorBlue = primaryColorBlue
        self.secondaryColorRed = secondaryColorRed
        self.secondaryColorGreen = secondaryColorGreen
        self.secondaryColorBlue = secondaryColorBlue
        self.textColorRed = textColorRed
        self.textColorGreen = textColorGreen
        self.textColorBlue = textColorBlue
        self.processingColorRed = processingColorRed
        self.processingColorGreen = processingColorGreen
        self.processingColorBlue = processingColorBlue
        self.processingAccentColorRed = processingAccentColorRed
        self.processingAccentColorGreen = processingAccentColorGreen
        self.processingAccentColorBlue = processingAccentColorBlue
        self.preferredFont = preferredFont
        self.surfaceFinish = surfaceFinish
    }

    func toAppearanceSettings() -> AppearanceSettings {
        AppearanceSettings(
            backgroundColorRed: backgroundColorRed,
            backgroundColorGreen: backgroundColorGreen,
            backgroundColorBlue: backgroundColorBlue,
            primaryColorRed: primaryColorRed,
            primaryColorGreen: primaryColorGreen,
            primaryColorBlue: primaryColorBlue,
            secondaryColorRed: secondaryColorRed,
            secondaryColorGreen: secondaryColorGreen,
            secondaryColorBlue: secondaryColorBlue,
            textColorRed: textColorRed,
            textColorGreen: textColorGreen,
            textColorBlue: textColorBlue,
            surfaceFinish: surfaceFinish,
            processingColorRed: processingColorRed,
            processingColorGreen: processingColorGreen,
            processingColorBlue: processingColorBlue,
            processingAccentColorRed: processingAccentColorRed,
            processingAccentColorGreen: processingAccentColorGreen,
            processingAccentColorBlue: processingAccentColorBlue,
            preferredFont: preferredFont
        )
    }
}

enum ReactAppearanceColorPickerField: String {
    case background
    case primary
    case secondary
    case text
}

struct ReactAppearanceColorPickerRequest {
    let field: ReactAppearanceColorPickerField
    let red: Double
    let green: Double
    let blue: Double

    init?(raw: [String: Any]) {
        func component(_ key: String) -> Double? {
            guard let value = (raw[key] as? NSNumber)?.doubleValue, value.isFinite else { return nil }
            guard value >= 0, value <= 1 else { return nil }
            return value
        }
        guard
            let rawField = raw["fieldId"] as? String,
            let field = ReactAppearanceColorPickerField(rawValue: rawField),
            let red = component("red"),
            let green = component("green"),
            let blue = component("blue")
        else { return nil }
        self.field = field
        self.red = red
        self.green = green
        self.blue = blue
    }
}

@MainActor
final class ReactAppearanceSettingsWebView: NSObject {
    let webView: WKWebView

    var onReady: (() -> Void)?
    var onPreviewDraft: ((ReactAppearanceSettingsDraftPayload) -> Void)?
    var onSaveDraft: ((String, ReactAppearanceSettingsDraftPayload) -> Void)?
    var onCancelDraft: ((String) -> Void)?
    var onResetDraft: ((String) -> Void)?
    var onOpenColorPicker: ((ReactAppearanceColorPickerRequest) -> Void)?
    var onMalformedIntent: ((String) -> Void)?

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }

        super.init()

        configuration.userContentController.add(
            ReactAppearanceSettingsWeakScriptMessageHandler(self),
            name: "basilAppearanceSettingsBridge"
        )
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[APPEARANCE_SETTINGS_WEB] Bundle.main.resourceURL is nil", context: "ReactAppearanceSettingsWebView")
            #endif
            return
        }
        let webAssetsFolder = resourceURL.appendingPathComponent("SettingsWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/appearance-settings.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            #if DEBUG
            DevLogger.shared.error("[APPEARANCE_SETTINGS_WEB] Staged HTML not found at \(htmlURL.path)", context: "ReactAppearanceSettingsWebView")
            #endif
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
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
                DevLogger.shared.error("[APPEARANCE_SETTINGS_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "ReactAppearanceSettingsWebView")
                #endif
            }
        }
    }

    func markReadyFromReact() {
        onReady?()
    }

    func tearDown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "basilAppearanceSettingsBridge")
    }

    fileprivate func handleScriptMessage(_ message: WKScriptMessage) {
        guard message.name == "basilAppearanceSettingsBridge",
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
        case "previewDraft":
            guard let rawDraft = body["draft"] as? [String: Any],
                  let payload = ReactAppearanceSettingsDraftPayload(raw: rawDraft) else {
                onMalformedIntent?("previewDraft")
                return
            }
            onPreviewDraft?(payload)
        case "saveDraft":
            guard let requestId = body["requestId"] as? String,
                  let rawDraft = body["draft"] as? [String: Any],
                  let payload = ReactAppearanceSettingsDraftPayload(raw: rawDraft) else {
                onMalformedIntent?("saveDraft")
                return
            }
            onSaveDraft?(requestId, payload)
        case "cancelDraft":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("cancelDraft")
                return
            }
            onCancelDraft?(requestId)
        case "resetDraft":
            guard let requestId = body["requestId"] as? String else {
                onMalformedIntent?("resetDraft")
                return
            }
            onResetDraft?(requestId)
        case "openColorPicker":
            guard let request = ReactAppearanceColorPickerRequest(raw: body) else {
                onMalformedIntent?("openColorPicker")
                return
            }
            onOpenColorPicker?(request)
        default:
            onMalformedIntent?(type)
        }
    }
}

private final class ReactAppearanceSettingsWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: ReactAppearanceSettingsWebView?

    init(_ target: ReactAppearanceSettingsWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
