import AppKit
@preconcurrency import WebKit
import SwiftUI

/// Hosts the React-based scheduled-run mini panel via WKWebView.
///
/// Mirrors ``AgentTaskResultWebView`` deliberately so future cross-platform
/// work (where the React bundle moves to other shells) only has to translate
/// one well-understood pattern.
///
/// The Swift side never owns the row state — that lives in the React app. We
/// only:
///   * load the staged HTML bundle from the .app resource bundle,
///   * push init config (ws url, port, theme, fonts) once load finishes,
///   * forward inbound JS bridge messages out as closures so the controller
///     can react (open the result widget, dismiss, panel-empty, resize).
@MainActor
final class ScheduledRunMiniPanelWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let webView: WKWebView

    /// Called when the user clicks a row. ``agentTaskId`` may be empty if the
    /// row is for a run that hasn't allocated an agent_task_id yet — the
    /// controller is responsible for ignoring/queuing in that case.
    var onOpenAgentTask: ((_ agentTaskId: String, _ runId: String) -> Void)?

    /// Called when the user clicks the row-level dismiss button.
    var onDismissRow: ((_ runId: String) -> Void)?

    /// Called when the user clicks the panel-level dismiss button.
    var onDismissPanel: (() -> Void)?

    /// Called when the user clicks the panel-level minimize button.
    /// The controller wires this to ``NSPanel.miniaturize(nil)`` so the
    /// panel is parked in the Dock while preserving its state (rows,
    /// WS connection, theme). Distinct from ``onDismissPanel`` which
    /// hides the panel by ordering it out.
    var onMinimizePanel: (() -> Void)?

    /// Called when the React side has settled into a zero-row state and
    /// wants the host NSPanel to order itself out.
    var onPanelEmpty: (() -> Void)?

    /// Called when the React side wants the host window resized to fit
    /// the current row count. Width is fixed by the React app; height
    /// floats with row count.
    var onRequestResize: ((_ width: CGFloat, _ height: CGFloat) -> Void)?

    /// Transparent overlay installed by ``installDragArea()``. Held so
    /// that we don't accidentally re-stack copies of it on a resize and
    /// so the controller can swap it out if we ever change the drag
    /// chrome region.
    private var dragAreaView: NSView?

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        let consoleScript = WKUserScript(
            source: """
                (function() {
                    var originalLog = console.log;
                    var originalError = console.error;
                    var originalWarn = console.warn;
                    console.log = function() {
                        window.webkit.messageHandlers.miniPanelLog.postMessage({level: 'log', message: Array.from(arguments).join(' ')});
                        originalLog.apply(console, arguments);
                    };
                    console.error = function() {
                        window.webkit.messageHandlers.miniPanelLog.postMessage({level: 'error', message: Array.from(arguments).join(' ')});
                        originalError.apply(console, arguments);
                    };
                    console.warn = function() {
                        window.webkit.messageHandlers.miniPanelLog.postMessage({level: 'warn', message: Array.from(arguments).join(' ')});
                        originalWarn.apply(console, arguments);
                    };
                    window.onerror = function(msg, url, line, col, error) {
                        window.webkit.messageHandlers.miniPanelLog.postMessage({level: 'error', message: 'JS Error: ' + msg + ' at ' + url + ':' + line + ':' + col});
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

        let contentController = configuration.userContentController
        contentController.add(self, name: "miniPanelBridge")
        contentController.add(self, name: "miniPanelLog")

        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    /// Overlay a transparent ``WindowDragAreaView`` across the panel header so AppKit can drag the borderless host without consuming the trailing controls.
    func installDragArea() {
        if let existing = dragAreaView {
            existing.removeFromSuperview()
            dragAreaView = nil
        }
        let topGutter = WebKitWindowChromeAppearance.frameInset
        let headerInnerHeight: CGFloat = 36
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
        self.dragAreaView = dragView
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[ScheduledRunMiniPanelWebView] Could not get bundle resource URL", context: "ScheduledRunMiniPanel")
            #endif
            return
        }

        let webAssetsFolder = resourceURL.appendingPathComponent("ScheduledRunMiniPanelAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/scheduled-run-mini-panel.html")

        #if DEBUG
        DevLogger.shared.info("[ScheduledRunMiniPanelWebView] Loading HTML from: \(htmlURL.path)", context: "ScheduledRunMiniPanel")
        #endif

        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            #if DEBUG
            DevLogger.shared.error("[ScheduledRunMiniPanelWebView] HTML file NOT found at: \(htmlURL.path)", context: "ScheduledRunMiniPanel")
            #endif
        }
    }

    // MARK: - Swift → JS

    func sendInit(port: Int) {
        let wsUrl = "ws://localhost:\(port)/ws"

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

        let config: [String: Any] = [
            "wsUrl": wsUrl,
            "port": port,
            "theme": theme,
            "fonts": fonts,
        ]
        callJS("window.basilMiniPanel.onInit", args: config)
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
        callJS("window.basilMiniPanel.onThemeChanged", args: theme, fonts)
    }

    private func callJS(_ function: String, args: Any...) {
        guard let argsData = args.map({ value -> String? in
            if let data = try? JSONSerialization.data(withJSONObject: value),
               let str = String(data: data, encoding: .utf8) {
                return str
            }
            return nil
        }) as? [String] else { return }

        let argsString = argsData.joined(separator: ", ")
        let js = "\(function)(\(argsString))"

        webView.evaluateJavaScript(js) { _, error in
            if let error = error {
                #if DEBUG
                DevLogger.shared.error("[ScheduledRunMiniPanelWebView] JS eval error: \(error)", context: "ScheduledRunMiniPanel")
                #endif
            }
        }
    }

    private func colorToHex(_ color: NSColor) -> String {
        guard let rgbColor = color.usingColorSpace(.sRGB) else {
            return "#000000"
        }
        let r = Int(rgbColor.redComponent * 255)
        let g = Int(rgbColor.greenComponent * 255)
        let b = Int(rgbColor.blueComponent * 255)
        return String(format: "#%02X%02X%02X", r, g, b)
    }

    private func colorToHex(_ color: SwiftUI.Color) -> String {
        return colorToHex(NSColor(color))
    }

    /// Returns the color's sRGB components as a comma-separated triplet
    /// suitable for CSS ``rgba(<triplet>, <alpha>)`` calls (e.g. the
    /// pulse halo on the running-status indicator). Falls back to the
    /// default --primary-rgb fallback baked into panel.css when sRGB
    /// conversion fails, so callers always have a usable triplet.
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
        return colorToRgbTriplet(NSColor(color))
    }

    // MARK: - WKScriptMessageHandler

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            handleMessage(name: message.name, body: message.body)
        }
    }

    private func handleMessage(name: String, body: Any) {
        if name == "miniPanelLog" {
            if let dict = body as? [String: String] {
                let level = dict["level"] ?? "log"
                let msg = dict["message"] ?? ""
                #if DEBUG
                DevLogger.shared.info("[ScheduledRunMiniPanelWebView JS \(level.uppercased())] \(msg)", context: "ScheduledRunMiniPanel")
                #endif
            }
            return
        }

        guard name == "miniPanelBridge", let dict = body as? [String: Any], let type = dict["type"] as? String else {
            return
        }

        switch type {
        case "openAgentTaskInResultWidget":
            let agentTaskId = (dict["agentTaskId"] as? String) ?? ""
            let runId = (dict["runId"] as? String) ?? ""
            onOpenAgentTask?(agentTaskId, runId)
        case "dismissRow":
            if let runId = dict["runId"] as? String {
                onDismissRow?(runId)
            }
        case "dismissPanel":
            onDismissPanel?()
        case "minimizePanel":
            // Forwarded by ``bridge.ts::minimizePanel`` when the user
            // clicks the React header's ``−`` button (or any future
            // wiring that wants to dock the panel programmatically).
            // The controller forwards this to NSPanel.miniaturize.
            onMinimizePanel?()
        case "panelEmpty":
            onPanelEmpty?()
        case "requestResize":
            if let width = dict["width"] as? CGFloat, let height = dict["height"] as? CGFloat {
                onRequestResize?(width, height)
            }
        default:
            #if DEBUG
            DevLogger.shared.info("[ScheduledRunMiniPanelWebView] Unknown message type: \(type)", context: "ScheduledRunMiniPanel")
            #endif
        }
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if DEBUG
        DevLogger.shared.info("[ScheduledRunMiniPanelWebView] Page loaded, sending init", context: "ScheduledRunMiniPanel")
        #endif
        let port = APIClient.shared.currentPort
        sendInit(port: port)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[ScheduledRunMiniPanelWebView] Navigation failed: \(error.localizedDescription)", context: "ScheduledRunMiniPanel")
        #endif
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[ScheduledRunMiniPanelWebView] Provisional navigation failed: \(error.localizedDescription)", context: "ScheduledRunMiniPanel")
        #endif
    }
}
