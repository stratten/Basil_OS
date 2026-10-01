import AppKit
@preconcurrency import WebKit
import SwiftUI

/// Hosts the React-based meeting-detected mini panel via WKWebView.
///
/// Mirrors ``ScheduledRunMiniPanelWebView`` intentionally: Swift owns the host
/// window lifecycle and bridge dispatch, while the web layer owns the rendered
/// card chrome so this prompt can move to other host shells later.
@MainActor
final class MeetingDetectedMiniPanelWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let webView: WKWebView

    var onStartMeeting: (() -> Void)?
    var onDismissMeeting: (() -> Void)?
    var onRequestResize: ((_ width: CGFloat, _ height: CGFloat) -> Void)?

    private var dragAreaView: NSView?
    private var isPageLoaded = false
    private var isReactReady = false
    private var hasSentInit = false
    private var pendingMeeting: DetectedMeetingInfo?

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
                        window.webkit.messageHandlers.meetingDetectedPanelLog.postMessage({level: 'log', message: Array.from(arguments).join(' ')});
                        originalLog.apply(console, arguments);
                    };
                    console.error = function() {
                        window.webkit.messageHandlers.meetingDetectedPanelLog.postMessage({level: 'error', message: Array.from(arguments).join(' ')});
                        originalError.apply(console, arguments);
                    };
                    console.warn = function() {
                        window.webkit.messageHandlers.meetingDetectedPanelLog.postMessage({level: 'warn', message: Array.from(arguments).join(' ')});
                        originalWarn.apply(console, arguments);
                    };
                    window.onerror = function(msg, url, line, col, error) {
                        window.webkit.messageHandlers.meetingDetectedPanelLog.postMessage({level: 'error', message: 'JS Error: ' + msg + ' at ' + url + ':' + line + ':' + col});
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
        contentController.add(self, name: "meetingDetectedPanelBridge")
        contentController.add(self, name: "meetingDetectedPanelLog")

        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    func installDragArea() {
        if let existing = dragAreaView {
            existing.removeFromSuperview()
            dragAreaView = nil
        }

        let topGutter = WebKitWindowChromeAppearance.frameInset
        let headerInnerHeight: CGFloat = 40
        let dragView = WindowDragAreaView(trailingInteractiveWidth: 76)
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: topGutter + headerInnerHeight),
        ])
        self.dragAreaView = dragView
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[MeetingDetectedMiniPanelWebView] Could not get bundle resource URL", context: "MeetingDetectedMiniPanel")
            #endif
            return
        }

        let webAssetsFolder = resourceURL.appendingPathComponent("MeetingDetectedMiniPanelAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/meeting-detected-mini-panel.html")

        #if DEBUG
        DevLogger.shared.info("[MeetingDetectedMiniPanelWebView] Loading HTML from: \(htmlURL.path)", context: "MeetingDetectedMiniPanel")
        #endif

        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            #if DEBUG
            DevLogger.shared.error("[MeetingDetectedMiniPanelWebView] HTML file NOT found at: \(htmlURL.path)", context: "MeetingDetectedMiniPanel")
            #endif
        }
    }

    // MARK: - Swift -> JS

    func sendInit() {
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

        callJS("window.basilMeetingDetectedPanel.onInit", args: ["theme": theme, "fonts": fonts])
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
        callJS("window.basilMeetingDetectedPanel.onThemeChanged", args: theme, fonts)
    }

    func sendMeeting(_ meeting: DetectedMeetingInfo) {
        pendingMeeting = meeting
        #if DEBUG
        DevLogger.shared.info(
            "[MeetingDetectedMiniPanelWebView] Queued meeting payload eventID=\(meeting.calendarEventID ?? "none") title=\(meeting.displayTitle)",
            context: "MeetingDetectedMiniPanel"
        )
        #endif
        flushPendingMeetingIfReady()
    }

    private func meetingPayload(for meeting: DetectedMeetingInfo) -> [String: Any] {
        [
            "appName": meeting.appName,
            "bundleID": meeting.bundleID,
            "mode": meeting.mode,
            "displayTitle": meeting.displayTitle,
            "calendarTitle": meeting.calendarTitle ?? "",
            "calendarName": meeting.calendarName ?? "",
            "calendarAttendees": meeting.calendarAttendees,
            "calendarJoinURL": meeting.calendarJoinURL?.absoluteString ?? "",
            "calendarHasCallInfo": meeting.calendarHasCallInfo,
            "calendarEventID": meeting.calendarEventID ?? "",
            "canJoinMeeting": meeting.canJoinMeeting,
        ]
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
                DevLogger.shared.error("[MeetingDetectedMiniPanelWebView] JS eval error: \(error)", context: "MeetingDetectedMiniPanel")
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

    // MARK: - WKScriptMessageHandler

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            handleMessage(name: message.name, body: message.body)
        }
    }

    private func handleMessage(name: String, body: Any) {
        if name == "meetingDetectedPanelLog" {
            if let dict = body as? [String: String] {
                let level = dict["level"] ?? "log"
                let msg = dict["message"] ?? ""
                #if DEBUG
                DevLogger.shared.info("[MeetingDetectedMiniPanelWebView JS \(level.uppercased())] \(msg)", context: "MeetingDetectedMiniPanel")
                #endif
            }
            return
        }

        guard name == "meetingDetectedPanelBridge", let dict = body as? [String: Any], let type = dict["type"] as? String else {
            return
        }

        switch type {
        case "reactReady":
            #if DEBUG
            DevLogger.shared.info("[MeetingDetectedMiniPanelWebView] React ready received", context: "MeetingDetectedMiniPanel")
            #endif
            isReactReady = true
            sendInitIfReady()
            flushPendingMeetingIfReady()
        case "startMeeting":
            onStartMeeting?()
        case "dismissMeeting":
            onDismissMeeting?()
        case "requestResize":
            if let width = dict["width"] as? CGFloat, let height = dict["height"] as? CGFloat {
                onRequestResize?(width, height)
            }
        default:
            #if DEBUG
            DevLogger.shared.info("[MeetingDetectedMiniPanelWebView] Unknown message type: \(type)", context: "MeetingDetectedMiniPanel")
            #endif
        }
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if DEBUG
        DevLogger.shared.info("[MeetingDetectedMiniPanelWebView] Page loaded, sending init", context: "MeetingDetectedMiniPanel")
        #endif
        isPageLoaded = true
        sendInitIfReady()
        flushPendingMeetingIfReady()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[MeetingDetectedMiniPanelWebView] Navigation failed: \(error.localizedDescription)", context: "MeetingDetectedMiniPanel")
        #endif
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[MeetingDetectedMiniPanelWebView] Provisional navigation failed: \(error.localizedDescription)", context: "MeetingDetectedMiniPanel")
        #endif
    }

    private func sendInitIfReady() {
        guard isPageLoaded, isReactReady, !hasSentInit else { return }
        hasSentInit = true
        sendInit()
    }

    private func flushPendingMeetingIfReady() {
        guard isPageLoaded, isReactReady else {
            #if DEBUG
            if pendingMeeting != nil {
                DevLogger.shared.info(
                    "[MeetingDetectedMiniPanelWebView] Holding meeting payload until ready pageLoaded=\(isPageLoaded) reactReady=\(isReactReady)",
                    context: "MeetingDetectedMiniPanel"
                )
            }
            #endif
            return
        }
        guard let meeting = pendingMeeting else { return }
        #if DEBUG
        DevLogger.shared.info(
            "[MeetingDetectedMiniPanelWebView] Flushing meeting payload eventID=\(meeting.calendarEventID ?? "none") title=\(meeting.displayTitle)",
            context: "MeetingDetectedMiniPanel"
        )
        #endif
        callJS("window.basilMeetingDetectedPanel.onMeetingChanged", args: meetingPayload(for: meeting))
    }
}
