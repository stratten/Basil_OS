import AppKit
@preconcurrency import WebKit
import SwiftUI

@MainActor
final class AmbientSuggestionsPanelWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let webView: WKWebView
    var onAcceptSuggestion: ((_ suggestionId: String) -> Void)?
    var onRejectSuggestion: ((_ suggestionId: String) -> Void)?
    var onDismissPanel: (() -> Void)?
    var onMinimizePanel: (() -> Void)?
    var onToggleCollapsePanel: ((_ compactSize: NSSize?) -> Void)?
    var onRequestResize: ((_ width: CGFloat, _ height: CGFloat) -> Void)?
    var onRuntimeChanged: (() -> Void)?

    private var dragAreaView: NSView?
    private var hasReceivedReadyAck = false
    private var initRetryGeneration = UUID()
    private let maxPortRetries = 30
    private let maxInitAckRetries = 10

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        let consoleScript = WKUserScript(
            source: """
                (function() {
                    var originalLog = console.log;
                    var originalError = console.error;
                    var originalWarn = console.warn;
                    function forward(level, args) {
                        try {
                            window.webkit.messageHandlers.ambientSuggestionsLog.postMessage({
                                level: level,
                                message: Array.from(args).join(' ')
                            });
                        } catch (_) {}
                    }
                    console.log = function() {
                        forward('log', arguments);
                        originalLog.apply(console, arguments);
                    };
                    console.error = function() {
                        forward('error', arguments);
                        originalError.apply(console, arguments);
                    };
                    console.warn = function() {
                        forward('warn', arguments);
                        originalWarn.apply(console, arguments);
                    };
                    window.onerror = function(msg, url, line, col) {
                        forward('error', ['JS Error: ' + msg + ' at ' + url + ':' + line + ':' + col]);
                        return false;
                    };
                })();
                """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: false
        )
        configuration.userContentController.addUserScript(consoleScript)

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView

        super.init()

        configuration.userContentController.add(self, name: "ambientSuggestionsBridge")
        configuration.userContentController.add(self, name: "ambientSuggestionsLog")
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    func installDragArea() {
        dragAreaView?.removeFromSuperview()
        let topGutter: CGFloat = 3
        let headerInnerHeight: CGFloat = 34
        let headerHeight = topGutter + headerInnerHeight
        let dragView = WindowDragAreaView(trailingInteractiveWidth: 76)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: headerHeight),
        ])
        dragAreaView = dragView
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else { return }
        let webAssetsFolder = resourceURL.appendingPathComponent("AmbientSuggestionsPanelAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/ambient-suggestions-panel.html")
        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            DevLogger.shared.error("[AmbientSuggestionsPanelWebView] HTML file not found: \(htmlURL.path)", context: "AmbientSuggestions")
        }
    }

    func sendInit(port: Int) {
        var theme = AestheticWebPayload.themePayload()
        theme["processingRgb"] = colorToRgbTriplet(AestheticSystem.Colors.processingBase)
        let baseFontName = AestheticSystem.Typography.preferredFontName
        let mediumFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica"
            : baseFontName.replacingOccurrences(of: "-Light", with: "")
        let boldFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica-Bold"
            : baseFontName.replacingOccurrences(of: "-Light", with: "-Bold")
        let config: [String: Any] = [
            "port": port,
            "theme": theme,
            "fonts": [
                "fontFamily": baseFontName,
                "fontFamilyMedium": mediumFontName,
                "fontFamilyBold": boldFontName,
            ],
        ]
        callJS("window.basilAmbientSuggestions.onInit", args: config)
    }

    func sendInitWhenPortReady(portAttempt: Int = 0, ackAttempt: Int = 0, generation: UUID? = nil) {
        let activeGeneration = generation ?? initRetryGeneration
        guard activeGeneration == initRetryGeneration else { return }
        guard !hasReceivedReadyAck else { return }

        let port = APIClient.shared.currentPort
        guard port > 0 else {
            if portAttempt < maxPortRetries {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                    self?.sendInitWhenPortReady(
                        portAttempt: portAttempt + 1,
                        ackAttempt: ackAttempt,
                        generation: activeGeneration
                    )
                }
            } else {
                DevLogger.shared.error("[AmbientSuggestionsPanelWebView] API port unavailable; init not sent", context: "AmbientSuggestions")
            }
            return
        }

        sendInit(port: port)

        if ackAttempt < maxInitAckRetries {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                guard let self else { return }
                guard !self.hasReceivedReadyAck else { return }
                DevLogger.shared.info("[AmbientSuggestionsPanelWebView] Retrying init waiting for React ack (attempt \(ackAttempt + 1))", context: "AmbientSuggestions")
                self.sendInitWhenPortReady(
                    portAttempt: portAttempt,
                    ackAttempt: ackAttempt + 1,
                    generation: activeGeneration
                )
            }
        } else {
            DevLogger.shared.error("[AmbientSuggestionsPanelWebView] React did not acknowledge init", context: "AmbientSuggestions")
        }
    }

    func sendThemeChanged() {
        var theme = AestheticWebPayload.themePayload()
        theme["processingRgb"] = colorToRgbTriplet(AestheticSystem.Colors.processingBase)
        let baseFontName = AestheticSystem.Typography.preferredFontName
        let mediumFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica"
            : baseFontName.replacingOccurrences(of: "-Light", with: "")
        let boldFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica-Bold"
            : baseFontName.replacingOccurrences(of: "-Light", with: "-Bold")
        let fonts: [String: Any] = [
            "fontFamily": baseFontName,
            "fontFamilyMedium": mediumFontName,
            "fontFamilyBold": boldFontName,
        ]
        callJS("window.basilAmbientSuggestions.onThemeChanged", args: theme, fonts)
    }

    func addSuggestion(_ suggestion: AmbientSuggestionRecord) {
        guard let data = try? JSONEncoder().encode(suggestion),
              let object = try? JSONSerialization.jsonObject(with: data) else {
            return
        }
        callJS("window.basilAmbientSuggestions.upsertSuggestion", args: object)
    }

    func removeSuggestion(_ suggestionId: String) {
        callJS("window.basilAmbientSuggestions.removeSuggestion", args: suggestionId)
    }

    func sendStatusChanged(_ status: [String: Any]) {
        callJS("window.basilAmbientSuggestions.statusChanged", args: status)
    }

    func sendModelSelected(_ modelId: String) {
        callJS("window.basilAmbientSuggestions.modelSelected", args: modelId)
    }

    private func callJS(_ function: String, args: Any...) {
        let argsData = args.compactMap { value -> String? in
            if let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed]),
               let str = String(data: data, encoding: .utf8) {
                return str
            }
            return nil
        }
        let js = "\(function)(\(argsData.joined(separator: ", ")))"
        webView.evaluateJavaScript(js) { _, error in
            if let error = error {
                DevLogger.shared.error("[AmbientSuggestionsPanelWebView] JS eval error: \(error)", context: "AmbientSuggestions")
            }
        }
    }

    private func colorToHex(_ color: NSColor) -> String {
        guard let rgbColor = color.usingColorSpace(.sRGB) else {
            return "#000000"
        }
        return String(
            format: "#%02X%02X%02X",
            Int(rgbColor.redComponent * 255),
            Int(rgbColor.greenComponent * 255),
            Int(rgbColor.blueComponent * 255)
        )
    }

    private func colorToHex(_ color: SwiftUI.Color) -> String {
        colorToHex(NSColor(color))
    }

    private func colorToRgbTriplet(_ color: NSColor) -> String {
        guard let rgbColor = color.usingColorSpace(.sRGB) else {
            return "29, 78, 216"
        }
        let r = Int(rgbColor.redComponent * 255)
        let g = Int(rgbColor.greenComponent * 255)
        let b = Int(rgbColor.blueComponent * 255)
        return "\(r), \(g), \(b)"
    }

    private func colorToRgbTriplet(_ color: SwiftUI.Color) -> String {
        colorToRgbTriplet(NSColor(color))
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            handleMessage(name: message.name, body: message.body)
        }
    }

    private func handleMessage(name: String, body: Any) {
        if name == "ambientSuggestionsLog" {
            if let dict = body as? [String: String] {
                let level = dict["level"] ?? "log"
                let message = dict["message"] ?? ""
                if level == "error" {
                    DevLogger.shared.error("[AmbientSuggestionsPanel JS] \(message)", context: "AmbientSuggestions")
                } else if level == "warn" {
                    DevLogger.shared.warning("[AmbientSuggestionsPanel JS] \(message)", context: "AmbientSuggestions")
                } else {
                    DevLogger.shared.info("[AmbientSuggestionsPanel JS] \(message)", context: "AmbientSuggestions")
                }
            }
            return
        }
        guard name == "ambientSuggestionsBridge",
              let dict = body as? [String: Any],
              let type = dict["type"] as? String else {
            return
        }
        switch type {
        case "ambientPanelReady":
            hasReceivedReadyAck = true
            DevLogger.shared.info("[AmbientSuggestionsPanelWebView] React ready ack received", context: "AmbientSuggestions")
            let port = APIClient.shared.currentPort
            if port > 0 {
                sendInit(port: port)
            }
        case "acceptSuggestion":
            if let suggestionId = dict["suggestionId"] as? String {
                onAcceptSuggestion?(suggestionId)
            }
        case "rejectSuggestion":
            if let suggestionId = dict["suggestionId"] as? String {
                onRejectSuggestion?(suggestionId)
            }
        case "dismissPanel":
            onDismissPanel?()
        case "minimizePanel":
            onMinimizePanel?()
        case "toggleCollapsePanel":
            let compactSize: NSSize?
            if let size = dict["compactSize"] as? [String: Any],
               let width = size["width"] as? CGFloat,
               let height = size["height"] as? CGFloat {
                compactSize = NSSize(width: width, height: height)
            } else {
                compactSize = nil
            }
            onToggleCollapsePanel?(compactSize)
        case "ambientRuntimeChanged":
            onRuntimeChanged?()
        case "showModelPicker":
            guard let models = dict["models"] as? [[String: Any]],
                  let selectedModelId = dict["selectedModelId"] as? String,
                  let anchorRect = dict["anchorRect"] as? [String: Any] else {
                return
            }
            showModelPicker(models: models, selectedModelId: selectedModelId, anchorRect: anchorRect)
        case "requestResize":
            if let width = dict["width"] as? CGFloat, let height = dict["height"] as? CGFloat {
                onRequestResize?(width, height)
            }
        default:
            break
        }
    }

    private func showModelPicker(models: [[String: Any]], selectedModelId: String, anchorRect: [String: Any]) {
        let localModels = models.filter { ($0["isLocal"] as? Bool) == true }
        let apiModels = models.filter { ($0["isLocal"] as? Bool) != true }
        let menu = NSMenu()
        appendModelSection(title: "Local Models", models: localModels, selectedModelId: selectedModelId, to: menu)
        if !localModels.isEmpty && !apiModels.isEmpty {
            menu.addItem(.separator())
        }
        appendModelSection(title: "API Models", models: apiModels, selectedModelId: selectedModelId, to: menu)
        guard menu.items.contains(where: { $0.action == #selector(handleModelPickerSelection(_:)) }) else {
            return
        }

        let x = cgFloat(from: anchorRect["x"]) ?? 0
        let y = cgFloat(from: anchorRect["y"]) ?? 0
        let height = cgFloat(from: anchorRect["height"]) ?? 0
        let anchorPointInWebView = NSPoint(x: x, y: webView.bounds.height - y - height)
        guard let window = webView.window else {
            menu.popUp(positioning: nil, at: anchorPointInWebView, in: webView)
            return
        }

        let anchorPointInWindow = webView.convert(anchorPointInWebView, to: nil)
        let anchorPointOnScreen = window.convertToScreen(
            NSRect(origin: anchorPointInWindow, size: .zero)
        ).origin
        menu.popUp(positioning: nil, at: anchorPointOnScreen, in: nil)
    }

    private func appendModelSection(title: String, models: [[String: Any]], selectedModelId: String, to menu: NSMenu) {
        guard !models.isEmpty else { return }
        let header = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        for model in models {
            guard let modelId = model["id"] as? String else { continue }
            let displayName = shortModelLabel(model["displayName"] as? String ?? modelId)
            let prefix = modelId == selectedModelId ? "* " : "  "
            let item = NSMenuItem(title: "\(prefix)\(displayName)", action: #selector(handleModelPickerSelection(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = modelId
            menu.addItem(item)
        }
    }

    @objc private func handleModelPickerSelection(_ sender: NSMenuItem) {
        guard let modelId = sender.representedObject as? String else { return }
        sendModelSelected(modelId)
    }

    private func shortModelLabel(_ rawName: String) -> String {
        let trimmed = rawName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasSuffix(")"),
              let openParen = trimmed.lastIndex(of: "(") else {
            return trimmed
        }
        let stripped = trimmed[..<openParen].trimmingCharacters(in: .whitespacesAndNewlines)
        return stripped.isEmpty ? trimmed : stripped
    }

    private func cgFloat(from value: Any?) -> CGFloat? {
        if let number = value as? NSNumber {
            return CGFloat(truncating: number)
        }
        if let double = value as? Double {
            return CGFloat(double)
        }
        if let int = value as? Int {
            return CGFloat(int)
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        hasReceivedReadyAck = false
        initRetryGeneration = UUID()
        sendInitWhenPortReady(generation: initRetryGeneration)
    }
}
