import AppKit
@preconcurrency import WebKit

@MainActor
final class AudioFileUploadWebView: NSObject {
    let webView: WKWebView

    var onIntent: (([String: Any]) -> Void)?
    var onReady: (() -> Void)?

    private(set) var hasReceivedReadyAck = false
    private var initRetryGeneration = UUID()
    private var pendingInitEvent: [String: Any]?

    override init() {
        let configuration = BasilWebViewConfigurationFactory.makeConfiguration()
        webView = FirstClickWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }

        super.init()

        configuration.userContentController.add(AudioFileUploadWeakScriptMessageHandler(self), name: "audioFileUploadBridge")
        webView.navigationDelegate = self
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[AUDIO_UPLOAD_WEB] Bundle.main.resourceURL is nil", context: "AudioFileUploadWebView")
            #endif
            return
        }
        let webAssetsFolder = resourceURL.appendingPathComponent("TranscriptionWidgetWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/audio-file-upload.html")
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            #if DEBUG
            DevLogger.shared.error("[AUDIO_UPLOAD_WEB] Staged HTML not found at \(htmlURL.path)", context: "AudioFileUploadWebView")
            #endif
            return
        }
        webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
    }

    func callJS(_ function: String, args: Any...) {
        webView.callBasilFunction(
            function,
            args: args,
            logTag: "AUDIO_UPLOAD_WEB",
            logContext: "AudioFileUploadWebView"
        )
    }

    func markReadyFromReact() {
        guard !hasReceivedReadyAck else { return }
        hasReceivedReadyAck = true
        onReady?()
    }

    func sendInitWhenReady(event: [String: Any], maxRetries: Int = 20, interval: TimeInterval = 0.35) {
        let generation = UUID()
        initRetryGeneration = generation
        pendingInitEvent = event
        attemptSendInit(generation: generation, remainingRetries: maxRetries, interval: interval)
    }

    private func attemptSendInit(generation: UUID, remainingRetries: Int, interval: TimeInterval) {
        guard generation == initRetryGeneration else { return }
        guard let event = pendingInitEvent else { return }
        callJS("window.basilAudioFileUpload && window.basilAudioFileUpload.onEvent", args: event)
        if hasReceivedReadyAck { return }
        guard remainingRetries > 0 else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + interval) { [weak self] in
            self?.attemptSendInit(generation: generation, remainingRetries: remainingRetries - 1, interval: interval)
        }
    }

    func tearDown() {
        initRetryGeneration = UUID()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "audioFileUploadBridge")
    }
}

extension AudioFileUploadWebView: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        hasReceivedReadyAck = false
        initRetryGeneration = UUID()
        pendingInitEvent = nil
    }
}

private final class AudioFileUploadWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: AudioFileUploadWebView?

    init(_ target: AudioFileUploadWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.handleScriptMessage(message)
    }
}
