import AppKit
@preconcurrency import WebKit
import SwiftUI

private struct TranscriptionModelPickerPopover: View {
    let apiModels: [TranscriptionModelOption]
    let localModels: [TranscriptionModelOption]
    let selectedModelId: String
    let onSelection: (String) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                modelSection("API Models", models: apiModels)
                if !apiModels.isEmpty && !localModels.isEmpty {
                    Divider()
                        .overlay(AestheticSystem.Colors.secondary.opacity(0.18))
                        .padding(.vertical, 5)
                }
                modelSection("Local Models", models: localModels)
            }
            .padding(5)
        }
        .background(AestheticSystem.Colors.backgroundPrimary)
    }

    @ViewBuilder
    private func modelSection(_ title: String, models: [TranscriptionModelOption]) -> some View {
        if !models.isEmpty {
            Text(title)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(AestheticSystem.Colors.textSecondary)
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
            ForEach(models) { model in
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

private final class TranscriptionDragAreaView: NSView {
    private weak var webView: WKWebView?
    private var isCompactContentHovered = false

    override var isFlipped: Bool { true }

    init(webView: WKWebView) {
        self.webView = webView
        super.init(frame: .zero)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func updateTrackingAreas() {
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(
            NSTrackingArea(
                rect: .zero,
            options: [.activeAlways, .inVisibleRect, .mouseEnteredAndExited, .mouseMoved],
                owner: self,
                userInfo: nil
            )
        )
        super.updateTrackingAreas()
    }

    override func mouseEntered(with event: NSEvent) {
        updateCompactHoverState(for: event)
    }

    override func mouseExited(with event: NSEvent) {
        publishHoverState(false)
    }

    override func mouseMoved(with event: NSEvent) {
        updateCompactHoverState(for: event)
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard bounds.contains(point) else { return nil }

        if bounds.width <= 240 {
            let compactContentSize = NSSize(width: 130, height: 65)
            let compactContentFrame = NSRect(
                x: (bounds.width - compactContentSize.width) / 2,
                y: (bounds.height - compactContentSize.height) / 2,
                width: compactContentSize.width,
                height: compactContentSize.height
            )
            guard compactContentFrame.contains(point) else { return self }

            let localPoint = NSPoint(
                x: point.x - compactContentFrame.minX,
                y: point.y - compactContentFrame.minY
            )
            let isLeftControl = localPoint.x <= 40 && (localPoint.y <= 24 || localPoint.y >= 41)
            let isRightControl = localPoint.x >= 90 && (localPoint.y <= 24 || localPoint.y >= 35)
            return isLeftControl || isRightControl ? nil : self
        }

        let topDragHeight = min(32, bounds.height)
        let leftControlBoundary: CGFloat = 112
        let rightBubbleBoundary: CGFloat = 72
        guard point.y <= topDragHeight,
              point.x >= leftControlBoundary,
              point.x <= bounds.maxX - rightBubbleBoundary else {
            return nil
        }
        return self
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseDown(with event: NSEvent) {
        window?.makeKey()
        window?.performDrag(with: event)
    }

    private func publishHoverState(_ isHovered: Bool) {
        guard isCompactContentHovered != isHovered else { return }
        isCompactContentHovered = isHovered
        webView?.evaluateJavaScript(
            "window.dispatchEvent(new CustomEvent('basilTranscriptionNativeHover', { detail: \(isHovered) }));"
        )
    }

    private func updateCompactHoverState(for event: NSEvent) {
        guard bounds.width <= 240 else {
            publishHoverState(false)
            return
        }
        let point = convert(event.locationInWindow, from: nil)
        let compactContentFrame = NSRect(
            x: (bounds.width - 130) / 2,
            y: (bounds.height - 65) / 2,
            width: 130,
            height: 65
        )
        publishHoverState(compactContentFrame.contains(point))
    }
}

@MainActor
final class TranscriptionWebView: NSObject {
    let webView: WKWebView

    var onResize: ((CGFloat, CGFloat) -> Void)?
    var onIntent: (([String: Any]) -> Void)?
    var onReady: (() -> Void)?

    private(set) var hasReceivedReadyAck = false
    private var initRetryGeneration = UUID()
    private var pendingInitPayload: Any?
    private var modelPickerSelection: ((String) -> Void)?
    private var modelPickerPopover: NSPopover?

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
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

        webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }

        super.init()

        configuration.userContentController.add(TranscriptionWeakScriptMessageHandler(self), name: "transcriptionWidgetBridge")
        configuration.userContentController.add(TranscriptionWeakScriptMessageHandler(self), name: "jsLog")
        webView.navigationDelegate = self

        let dragArea = TranscriptionDragAreaView(webView: webView)
        dragArea.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragArea)
        NSLayoutConstraint.activate([
            dragArea.topAnchor.constraint(equalTo: webView.topAnchor),
            dragArea.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragArea.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragArea.bottomAnchor.constraint(equalTo: webView.bottomAnchor),
        ])
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[TRANSCRIPTION_WIDGET_WEB] Bundle.main.resourceURL is nil", context: "TranscriptionWebView")
            #endif
            return
        }
        let webAssetsFolder = resourceURL.appendingPathComponent("TranscriptionWidgetWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/transcription-widget.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            #if DEBUG
            DevLogger.shared.error("[TRANSCRIPTION_WIDGET_WEB] Staged HTML not found at \(htmlURL.path)", context: "TranscriptionWebView")
            #endif
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
    }

    func showTranscriptionModelPicker(
        models: [TranscriptionModelOption],
        selectedModelId: String,
        anchorRect: [String: CGFloat],
        onSelection: @escaping (String) -> Void
    ) {
        let apiModels = models.filter(\.isApiModel)
        let localModels = models.filter { !$0.isApiModel }
        guard !apiModels.isEmpty || !localModels.isEmpty else {
            return
        }

        modelPickerPopover?.performClose(nil)
        let popover = NSPopover()
        popover.behavior = .transient
        popover.appearance = NativeModelPickerPopoverSupport.themedAppearance()
        popover.contentSize = NSSize(width: 210, height: min(260, max(70, 34 + (models.count * 28))))
        popover.contentViewController = NSHostingController(
            rootView: TranscriptionModelPickerPopover(
                apiModels: apiModels,
                localModels: localModels,
                selectedModelId: selectedModelId,
                onSelection: { [weak self, weak popover] modelId in
                    popover?.performClose(nil)
                    self?.modelPickerSelection?(modelId)
                    self?.modelPickerSelection = nil
                }
            )
        )
        modelPickerSelection = onSelection
        modelPickerPopover = popover
        let x = anchorRect["x"] ?? 0
        let y = anchorRect["y"] ?? 0
        let width = anchorRect["width"] ?? 0
        let height = anchorRect["height"] ?? 0
        let bridgedAnchor = NativeModelPickerPopoverSupport.anchorRect(
            webX: x,
            webY: y,
            width: width,
            height: height,
            hostBounds: webView.bounds,
            hostIsFlipped: webView.isFlipped
        )
        let anchor: NSRect
        if let window = webView.window {
            let pointInWindow = window.convertPoint(fromScreen: NSEvent.mouseLocation)
            let pointInWebView = webView.convert(pointInWindow, from: nil)
            anchor = NSRect(x: pointInWebView.x, y: pointInWebView.y, width: 1, height: 1)
        } else {
            anchor = bridgedAnchor
        }
        popover.show(relativeTo: anchor, of: webView, preferredEdge: .minY)
        NativeModelPickerPopoverSupport.paintThemedFrameBackground(of: popover)
    }

    func callJS(_ function: String, event: Any) {
        webView.callAsyncJavaScript(
            "\(function)(event)",
            arguments: ["event": event],
            in: nil,
            in: .page
        ) { result in
            if case .failure(let error) = result {
                #if DEBUG
                DevLogger.shared.error("[TRANSCRIPTION_WIDGET_WEB] JS eval error for \(function): \(error)", context: "TranscriptionWebView")
                #endif
            }
        }
    }

    func markReadyFromReact() {
        guard !hasReceivedReadyAck else { return }
        hasReceivedReadyAck = true
        onReady?()
    }

    func sendInitWhenReady(payload: Any, maxRetries: Int = 20, interval: TimeInterval = 0.35) {
        let generation = UUID()
        initRetryGeneration = generation
        pendingInitPayload = payload
        attemptSendInit(generation: generation, remainingRetries: maxRetries, interval: interval)
    }

    private func attemptSendInit(generation: UUID, remainingRetries: Int, interval: TimeInterval) {
        guard generation == initRetryGeneration else { return }
        guard let payload = pendingInitPayload else { return }
        callJS("window.basilTranscriptionWidget && window.basilTranscriptionWidget.onEvent", event: payload)
        if hasReceivedReadyAck { return }
        guard remainingRetries > 0 else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + interval) { [weak self] in
            self?.attemptSendInit(generation: generation, remainingRetries: remainingRetries - 1, interval: interval)
        }
    }

    func tearDown() {
        initRetryGeneration = UUID()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "transcriptionWidgetBridge")
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "jsLog")
    }
}

extension TranscriptionWebView: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        hasReceivedReadyAck = false
        initRetryGeneration = UUID()
        pendingInitPayload = nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        #if DEBUG
        DevLogger.shared.info("[TRANSCRIPTION_WIDGET_WEB] Navigation finished", context: "TranscriptionWebView")
        #endif
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        #if DEBUG
        DevLogger.shared.error("[TRANSCRIPTION_WIDGET_WEB] Navigation failed: \(error)", context: "TranscriptionWebView")
        #endif
    }
}

private final class TranscriptionWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: TranscriptionWebView?

    init(_ target: TranscriptionWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
