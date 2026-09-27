import AppKit
@preconcurrency import WebKit
import SwiftUI

struct AssistantSessionModelPickerOption: Hashable {
    let id: String
    let displayName: String
    let category: String
}

private struct AssistantSessionModelPickerPopover: View {
    let models: [AssistantSessionModelPickerOption]
    let selectedModelId: String?
    let onSelection: (String) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                modelSection("Local Models", category: "local")
                if models.contains(where: { $0.category == "local" }) && models.contains(where: { $0.category == "api" }) {
                    Divider()
                        .overlay(AestheticSystem.Colors.secondary.opacity(0.18))
                        .padding(.vertical, 5)
                }
                modelSection("API Models", category: "api")
            }
            .padding(5)
        }
        .background(AestheticSystem.Colors.backgroundPrimary)
    }

    @ViewBuilder
    private func modelSection(_ title: String, category: String) -> some View {
        let sectionModels = models.filter { $0.category == category }
        if !sectionModels.isEmpty {
            Text(title)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(AestheticSystem.Colors.textSecondary)
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
            ForEach(sectionModels, id: \.id) { model in
                Button {
                    onSelection(model.id)
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "checkmark")
                            .font(.system(size: 9, weight: .semibold))
                            .opacity(model.id == selectedModelId ? 1 : 0)
                        Text(model.displayName)
                            .font(.system(size: 10))
                            .foregroundColor(AestheticSystem.Colors.textPrimary)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 7)
                    .padding(.vertical, 5)
                    .background(
                        RoundedRectangle(cornerRadius: 4)
                            .fill(model.id == selectedModelId ? AestheticSystem.Colors.primary.opacity(0.1) : .clear)
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }
}

@MainActor
final class AssistantSessionWebView: NSObject {
    let webView: WKWebView

    var onResize: ((CGFloat, CGFloat) -> Void)?
    var onIntent: (([String: Any]) -> Void)?
    var onReady: (() -> Void)?
    var onModelPickerSelection: ((String) -> Void)?

    private(set) var hasReceivedReadyAck = false
    private var initRetryGeneration = UUID()
    private var pendingInitPayload: [String: Any]?
    private var modelPickerPopover: NSPopover?

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        let consoleForwardingScript = WKUserScript(
            source: """
            (function () {
              function forward(kind, args) {
                try {
                  window.webkit.messageHandlers.jsLog.postMessage({ kind: kind, message: Array.from(args).map(String).join(' ') });
                } catch (e) {}
              }
              const originalLog = console.log;
              const originalError = console.error;
              const originalWarn = console.warn;
              console.log = function () { forward('log', arguments); originalLog.apply(console, arguments); };
              console.error = function () { forward('error', arguments); originalError.apply(console, arguments); };
              console.warn = function () { forward('warn', arguments); originalWarn.apply(console, arguments); };
              window.onerror = function (message, source, lineno, colno, error) {
                forward('error', [message + ' @ ' + source + ':' + lineno + ':' + colno]);
              };
            })();
            """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        configuration.userContentController.addUserScript(consoleForwardingScript)

        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }

        super.init()

        configuration.userContentController.add(AssistantSessionWeakScriptMessageHandler(self), name: "assistantSessionBridge")
        configuration.userContentController.add(AssistantSessionWeakScriptMessageHandler(self), name: "jsLog")
        webView.navigationDelegate = self
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[ASSISTANT_SESSION_WEB] Bundle.main.resourceURL is nil", context: "AssistantSessionWebView")
            #endif
            return
        }
        let webAssetsFolder = resourceURL.appendingPathComponent("AssistantSessionWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/assistant-session.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            #if DEBUG
            DevLogger.shared.error("[ASSISTANT_SESSION_WEB] Staged HTML not found at \(htmlURL.path)", context: "AssistantSessionWebView")
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
                DevLogger.shared.error("[ASSISTANT_SESSION_WEB] callAsyncJavaScript failed for \(function): \(error)", context: "AssistantSessionWebView")
                #endif
            }
        }
    }

    func showNativeModelPicker(
        models: [AssistantSessionModelPickerOption],
        selectedModelId: String?,
        anchorRect: NSRect
    ) {
        guard !models.isEmpty else { return }
        modelPickerPopover?.performClose(nil)

        let popover = NSPopover()
        popover.behavior = .transient
        popover.appearance = NSAppearance(named: .aqua)
        popover.contentSize = NSSize(width: 210, height: min(260, max(70, 34 + (models.count * 28))))
        popover.contentViewController = NSHostingController(
            rootView: AssistantSessionModelPickerPopover(
                models: models,
                selectedModelId: selectedModelId,
                onSelection: { [weak self, weak popover] modelId in
                    popover?.performClose(nil)
                    self?.onModelPickerSelection?(modelId)
                    self?.modelPickerPopover = nil
                }
            )
        )
        modelPickerPopover = popover
        popover.show(relativeTo: anchorRect, of: webView, preferredEdge: .minY)
    }

    func markReadyFromReact() {
        guard !hasReceivedReadyAck else { return }
        hasReceivedReadyAck = true
        onReady?()
    }

    func sendInitWhenReady(payload: [String: Any], maxRetries: Int = 20, interval: TimeInterval = 0.35) {
        let generation = UUID()
        initRetryGeneration = generation
        pendingInitPayload = payload
        attemptSendInit(generation: generation, remainingRetries: maxRetries, interval: interval)
    }

    private func attemptSendInit(generation: UUID, remainingRetries: Int, interval: TimeInterval) {
        guard generation == initRetryGeneration else { return }
        guard let payload = pendingInitPayload else { return }
        callJS("window.basilAssistantSession && window.basilAssistantSession.onEvent", args: payload)
        if hasReceivedReadyAck { return }
        guard remainingRetries > 0 else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + interval) { [weak self] in
            self?.attemptSendInit(generation: generation, remainingRetries: remainingRetries - 1, interval: interval)
        }
    }

    func tearDown() {
        initRetryGeneration = UUID()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "assistantSessionBridge")
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "jsLog")
        modelPickerPopover?.performClose(nil)
        modelPickerPopover = nil
    }
}

extension AssistantSessionWebView: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        hasReceivedReadyAck = false
        initRetryGeneration = UUID()
        pendingInitPayload = nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION_WEB] Navigation finished", context: "AssistantSessionWebView")
        #endif
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[ASSISTANT_SESSION_WEB] Navigation failed: \(error)", context: "AssistantSessionWebView")
        #endif
    }
}

private final class AssistantSessionWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: AssistantSessionWebView?

    init(_ target: AssistantSessionWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
