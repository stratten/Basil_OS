import AppKit
@preconcurrency import WebKit

enum BasilBoardFileDropTarget: String {
    case home
    case conversation
    case todoWorkspace
}

enum BasilBoardVoiceCaptureSurface {
    case home
    case conversation

    var flowContext: String {
        switch self {
        case .home: return "basil_board_home"
        case .conversation: return "basil_board_conversation"
        }
    }

    var transcribePath: String {
        switch self {
        case .home: return "/api/v1/basil-board/home/transcribe"
        case .conversation: return "/api/v1/basil-board/conversation/transcribe"
        }
    }

    var audioFilename: String {
        switch self {
        case .home: return "home_turn.wav"
        case .conversation: return "conversation_turn.wav"
        }
    }

    var stateCallback: String {
        switch self {
        case .home: return "onVoiceCaptureState"
        case .conversation: return "onConversationVoiceCaptureState"
        }
    }

    var finishedCallback: String {
        switch self {
        case .home: return "onVoiceCaptureFinished"
        case .conversation: return "onConversationVoiceCaptureFinished"
        }
    }
}

enum BasilBoardWebViewEntryPage {
    case basilBoard
    case conversation

    var htmlRelativePath: String {
        switch self {
        case .basilBoard: return "src/entries/basil-board.html"
        case .conversation: return "src/entries/conversation.html"
        }
    }
}

enum BasilBoardConversationPresentation: String {
    case global
    case thread
}

@MainActor
final class BasilBoardWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate, ConversationDetachedThreadsObserver {
    let webView: WKWebView
    var dragAreaView: WindowDragAreaView?
    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onReady: (() -> Void)?
    var onDetachTab: ((String) -> Void)?
    var onBringTabToFront: ((String) -> Void)?
    var onOpenMeetingWorkspace: ((String) -> Void)?
    let detachedTabId: String?
    let entryPage: BasilBoardWebViewEntryPage
    let initialConversationId: String?
    let conversationPresentation: BasilBoardConversationPresentation
    var onCollapseRequested: (() -> Void)?
    var onExpandRequested: (() -> Void)?

    private var bridgeInitialized = false
    private var hasDeliveredThemeReady = false
    private var detachedTabIds: [String] = []
    private var detachedConversationIds: [String] = []
    private var pendingAgentTaskOriginNavigation: (originType: String, originId: String)?
    private var pendingConversationComposerFocus = false
    private let audioCaptureService = AudioCaptureService()
    private var voiceCaptureTask: Task<Void, Never>?
    private var activeVoiceCaptureSurface: BasilBoardVoiceCaptureSurface?
    private var armedFileDropTarget: BasilBoardFileDropTarget?
    private let maximumPastedImageCount = 10
    private let maximumPastedImageBytes = 20 * 1024 * 1024
    private var statusIconObserver: NSObjectProtocol?
    private let presentationObserverID = UUID()
    private var agentTaskResultEmbeddedHost: AgentTaskResultEmbeddedHost?
    private var isAgentTasksSurfaceActive = false
    private var isConversationSurfaceActive = false
    private let conversationPresentationObserverID = UUID()
    private(set) var meetingAssistantEmbeddedHost: MeetingAssistantEmbeddedHost?
    private var isMeetingsSurfaceActive = false
    private let meetingsPresentationObserverID = UUID()
    var meetingSessionCoordinatorProvider: () -> MeetingSessionCoordinator? = {
        (NSApp.delegate as? AppDelegate)?.statusBarManager?.windowCoordinator.meetingSessionCoordinator
    }
    private var filePreviewCoordinator: NativeArtifactFilePreviewCoordinator!
    weak var hostWindow: NSWindow?

    init(
        detachedTabId: String? = nil,
        entryPage: BasilBoardWebViewEntryPage = .basilBoard,
        initialConversationId: String? = nil,
        conversationPresentation: BasilBoardConversationPresentation = .global
    ) {
        self.detachedTabId = detachedTabId
        self.entryPage = entryPage
        self.initialConversationId = initialConversationId
        self.conversationPresentation = conversationPresentation

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

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView

        super.init()

        if conversationPresentation != .thread {
            let manager = DetachedConversationThreadWindowManager.shared
            detachedConversationIds = manager.detachedConversationIds
            manager.addObserver(self)
        }

        configuration.userContentController.add(self, name: "basilBoardBridge")
        configuration.userContentController.add(self, name: "jsLog")
        webView.navigationDelegate = self

        filePreviewCoordinator = NativeArtifactFilePreviewCoordinator(
            emit: { [weak self] name, payload in
                self?.emitBridgeCallback(name, payload: payload)
            },
            hostView: { [weak self] in self?.webView ?? NSView() }
        )

        webView.onFilesDropped = { [weak self] paths in
            guard let self else { return }
            switch armedFileDropTarget {
            case .home:
                emitBridgeCallback("onFilesPicked", payload: ["paths": paths])
            case .conversation:
                emitBridgeCallback("onConversationFilesPicked", payload: ["paths": paths])
            case .todoWorkspace:
                emitBridgeCallback("onTodoWorkspaceFilesPicked", payload: ["paths": paths])
            case nil:
                DevLogger.shared.warning(
                    "[BasilBoardWebView] Ignored file drop without an armed composer target",
                    context: "BasilBoard"
                )
            }
            armedFileDropTarget = nil
        }
        statusIconObserver = NotificationCenter.default.addObserver(
            forName: .basilStatusBarIconDidChange,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.emitCurrentStatusIcon()
            }
        }
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    deinit {
        if let statusIconObserver {
            NotificationCenter.default.removeObserver(statusIconObserver)
        }
        voiceCaptureTask?.cancel()
    }

    func installDragArea() {
        let headerHeight: CGFloat = 44
        let (leadingInteractiveWidth, trailingInteractiveWidth): (CGFloat, CGFloat) = switch entryPage {
        case .basilBoard:
            (84, 76)
        case .conversation:
            (109, 0)
        }
        let dragView = WindowDragAreaView(
            leadingInteractiveWidth: leadingInteractiveWidth,
            trailingInteractiveWidth: trailingInteractiveWidth
        )
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
            DevLogger.shared.error("[BasilBoardWebView] Missing bundle resource URL", context: "BasilBoard")
            return
        }

        let webAssetsFolder = resourceURL.appendingPathComponent("BasilBoardWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent(entryPage.htmlRelativePath)

        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            DevLogger.shared.error("[BasilBoardWebView] HTML file not found at \(htmlURL.path)", context: "BasilBoard")
        }
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.frameInfo.isMainFrame || message.name == "jsLog" else { return }
            handleMessage(name: message.name, body: message.body)
        }
    }

    func handleMessage(name: String, body: Any) {
        if name == "jsLog" {
            if let log = body as? [String: String] {
                DevLogger.shared.info("[BasilBoard JS \(log["level"] ?? "log")] \(log["message"] ?? "")", context: "BasilBoard")
            }
            return
        }

        guard name == "basilBoardBridge",
              let dict = body as? [String: Any],
              let type = dict["type"] as? String else {
            return
        }

        switch type {
        case "basilBoardReady":
            sendInitWhenPortReady()
        case "basilBoardThemeApplied":
            guard !hasDeliveredThemeReady else { return }
            hasDeliveredThemeReady = true
            onReady?()
        case "requestWindowClose":
            onClose?()
        case "requestWindowMinimize":
            onMinimize?()
        case "requestWindowCollapse":
            onCollapseRequested?()
        case "requestWindowExpand":
            onExpandRequested?()
        case "openExistingAgentTaskWidget":
            if let agentTaskId = dict["agentTaskId"] as? String {
                AgentTaskResultPresentationRouter.showExistingAgentTask(agentTaskId: agentTaskId)
            } else {
                emitWidgetLaunchFailed(reason: "missing_agent_task_id", message: "No agent task id provided.")
            }
        case "openConversationThreadWindow":
            guard let conversationId = dict["conversationId"] as? String,
                  !conversationId.isEmpty else {
                return
            }
            DetachedConversationThreadWindowManager.shared.open(
                conversationId: conversationId,
                originatingWindow: hostWindow
            )
        case "openExternalUrl":
            guard let value = dict["url"] as? String,
                  let url = URL(string: value),
                  ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? "") else {
                return
            }
            NSWorkspace.shared.open(url)
        case "copyToClipboard":
            if let text = dict["text"] as? String {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(text, forType: .string)
            }
        case "copyRichTextToClipboard":
            if let text = dict["text"] as? String {
                let pasteboard = NSPasteboard.general
                pasteboard.clearContents()
                let attributedString = MarkdownUtils.markdownToAttributedString(text)
                pasteboard.setString(attributedString.string, forType: .string)
                if MarkdownUtils.containsMarkdown(text),
                   let rtfData = attributedString.rtf(
                    from: NSRange(location: 0, length: attributedString.length),
                    documentAttributes: [:]
                   ) {
                    pasteboard.setData(rtfData, forType: .rtf)
                }
            }
        case "pickHomeFiles":
            let panel = NSOpenPanel()
            panel.allowsMultipleSelection = true
            panel.canChooseFiles = true
            panel.canChooseDirectories = true
            panel.canCreateDirectories = false
            panel.title = "Attach Files or Folders"
            panel.begin { [weak self] response in
                guard response == .OK, !panel.urls.isEmpty else { return }
                self?.emitBridgeCallback("onFilesPicked", payload: ["paths": panel.urls.map(\.path)])
            }
        case "pickConversationFiles":
            let panel = NSOpenPanel()
            panel.allowsMultipleSelection = true
            panel.canChooseFiles = true
            panel.canChooseDirectories = false
            panel.canCreateDirectories = false
            panel.title = "Attach Files"
            panel.begin { [weak self] response in
                guard response == .OK, !panel.urls.isEmpty else { return }
                self?.emitBridgeCallback(
                    "onConversationFilesPicked",
                    payload: ["paths": panel.urls.map(\.path)]
                )
            }
        case "pickTodoWorkspaceFiles":
            let panel = NSOpenPanel()
            panel.allowsMultipleSelection = true
            panel.canChooseFiles = true
            panel.canChooseDirectories = true
            panel.canCreateDirectories = false
            panel.title = "Attach Files or Folders"
            panel.begin { [weak self] response in
                guard response == .OK, !panel.urls.isEmpty else { return }
                self?.emitBridgeCallback(
                    "onTodoWorkspaceFilesPicked",
                    payload: ["paths": panel.urls.map(\.path)]
                )
            }
        case "pickTodoReferenceFiles":
            let panel = NSOpenPanel()
            panel.allowsMultipleSelection = true
            panel.canChooseFiles = true
            panel.canChooseDirectories = true
            panel.canCreateDirectories = false
            panel.title = "Attach Files or Folders to To-Do"
            panel.begin { [weak self] response in
                guard response == .OK, !panel.urls.isEmpty else { return }
                self?.emitBridgeCallback(
                    "onTodoReferenceFilesPicked",
                    payload: ["paths": panel.urls.map(\.path)]
                )
            }
        case "pickWorkspaceDirectory":
            guard let requestId = dict["requestId"] as? String,
                  !requestId.trimmingCharacters(in: .whitespaces).isEmpty else {
                return
            }
            let panel = NSOpenPanel()
            panel.allowsMultipleSelection = false
            panel.canChooseFiles = false
            panel.canChooseDirectories = true
            panel.canCreateDirectories = false
            panel.title = "Choose Workspace Folder"
            panel.begin { [weak self] response in
                guard response == .OK, let url = panel.urls.first else {
                    self?.emitBridgeCallback(
                        "onWorkspaceDirectoryPicked",
                        payload: ["requestId": requestId, "status": "canceled"]
                    )
                    return
                }
                switch WorkspaceDirectoryCanonicalizer.canonicalize(url) {
                case .success(let path):
                    self?.emitBridgeCallback(
                        "onWorkspaceDirectoryPicked",
                        payload: ["requestId": requestId, "status": "selected", "path": path]
                    )
                case .failure(let failure):
                    self?.emitBridgeCallback(
                        "onWorkspaceDirectoryPicked",
                        payload: ["requestId": requestId, "status": "error", "message": failure.userMessage]
                    )
                }
            }
        case "setBoardFileDropTarget":
            if let rawTarget = dict["target"] as? String {
                armedFileDropTarget = BasilBoardFileDropTarget(rawValue: rawTarget)
            } else {
                armedFileDropTarget = nil
            }
        case "saveConversationPastedImages":
            saveConversationPastedImages(dict["dataUrls"])
        case "startHomeVoiceCapture":
            startVoiceCapture(surface: .home)
        case "stopHomeVoiceCapture":
            finishVoiceCapture(surface: .home, canceled: false)
        case "cancelHomeVoiceCapture":
            finishVoiceCapture(surface: .home, canceled: true)
        case "startConversationVoiceCapture":
            startVoiceCapture(surface: .conversation)
        case "stopConversationVoiceCapture":
            finishVoiceCapture(surface: .conversation, canceled: false)
        case "cancelConversationVoiceCapture":
            finishVoiceCapture(surface: .conversation, canceled: true)
        case "detachBasilBoardTab":
            if let tabId = dict["tabId"] as? String, DetachedBasilBoardTabWindowManager.boardWindowTabIds.contains(tabId) {
                onDetachTab?(tabId)
            } else {
                DevLogger.shared.error("[BasilBoardWebView] Rejected detachBasilBoardTab for unrecognized tabId", context: "BasilBoard")
            }
        case "bringBasilBoardTabToFront":
            if let tabId = dict["tabId"] as? String, DetachedBasilBoardTabWindowManager.boardWindowTabIds.contains(tabId) {
                onBringTabToFront?(tabId)
            } else {
                DevLogger.shared.error("[BasilBoardWebView] Rejected bringBasilBoardTabToFront for unrecognized tabId", context: "BasilBoard")
            }
        case "openNativeBasilBoardTabWindow":
            guard let tabId = dict["tabId"] as? String else {
                DevLogger.shared.error(
                    "[BasilBoardWebView] Missing tabId for openNativeBasilBoardTabWindow",
                    context: "BasilBoard"
                )
                return
            }
            BasilBoardNativeTabWindowRegistry.open(tabId: tabId)
        case "openMeetingWorkspace":
            if let meetingId = dict["meetingId"] as? String, !meetingId.isEmpty {
                onOpenMeetingWorkspace?(meetingId)
            }
        case "activateBoardAgentTasksSurface":
            if !isAgentTasksSurfaceActive {
                isAgentTasksSurfaceActive = true
                AgentTaskResultPresentationCoordinator.shared.registerBoardVisible()
            }
            AgentTaskResultPresentationCoordinator.shared.addObserver(id: presentationObserverID) { [weak self] in
                self?.reconcileAgentTasksEmbedding()
            }
            reconcileAgentTasksEmbedding()
        case "deactivateBoardAgentTasksSurface":
            deactivateBoardAgentTasksSurface()
        case "activateBoardMeetingsSurface":
            if !isMeetingsSurfaceActive {
                isMeetingsSurfaceActive = true
                MeetingPresentationCoordinator.shared.registerBoardVisible()
            }
            MeetingPresentationCoordinator.shared.addObserver(id: meetingsPresentationObserverID) { [weak self] in
                self?.reconcileMeetingsEmbedding()
            }
            reconcileMeetingsEmbedding()
        case "deactivateBoardMeetingsSurface":
            deactivateBoardMeetingsSurface()
        case "activateBoardConversationSurface":
            if !isConversationSurfaceActive {
                isConversationSurfaceActive = true
                ConversationPresentationCoordinator.shared.registerBoardVisible()
            }
            ConversationPresentationCoordinator.shared.addObserver(id: conversationPresentationObserverID) { [weak self] in
                self?.emitBoardConversationAvailability()
            }
            emitBoardConversationAvailability()
        case "deactivateBoardConversationSurface":
            deactivateBoardConversationSurface()
        case "reportBoardChromeGeometry":
            if let contentLeft = dict["contentLeft"] as? NSNumber,
               let contentTop = dict["contentTop"] as? NSNumber {
                measuredContentLeft = CGFloat(contentLeft.doubleValue)
                measuredContentTop = CGFloat(contentTop.doubleValue)
            }
        case "previewFile":
            guard let requestId = dict["requestId"] as? String,
                  !requestId.isEmpty,
                  requestId.count <= 160 else {
                break
            }
            guard let path = dict["path"] as? String,
                  let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) else {
                filePreviewCoordinator.rejectFilePreviewRequest(
                    requestId: requestId,
                    path: dict["path"] as? String
                )
                break
            }
            filePreviewCoordinator.handleFilePreviewRequest(requestId: requestId, path: posixPath)
        case "clearFilePreview":
            if let requestId = dict["requestId"] as? String, !requestId.isEmpty {
                filePreviewCoordinator.clearActiveFilePreview(requestId: requestId)
            }
        case "setInlineNativePreviewFrame":
            guard let requestId = dict["requestId"] as? String,
                  !requestId.isEmpty,
                  let frame = dict["frame"] as? [String: Any],
                  let left = frame["left"] as? NSNumber,
                  let top = frame["top"] as? NSNumber,
                  let width = frame["width"] as? NSNumber, width.doubleValue > 0,
                  let height = frame["height"] as? NSNumber, height.doubleValue > 0,
                  let viewportWidth = frame["viewportWidth"] as? NSNumber, viewportWidth.doubleValue > 0,
                  let viewportHeight = frame["viewportHeight"] as? NSNumber, viewportHeight.doubleValue > 0,
                  let nativeFrame = filePreviewCoordinator.inlineNativePreviewFrame(
                    left: CGFloat(left.doubleValue),
                    top: CGFloat(top.doubleValue),
                    width: CGFloat(width.doubleValue),
                    height: CGFloat(height.doubleValue),
                    viewportWidth: CGFloat(viewportWidth.doubleValue),
                    viewportHeight: CGFloat(viewportHeight.doubleValue)
                  ) else {
                break
            }
            filePreviewCoordinator.presentInlinePDFPreview(requestId: requestId, frame: nativeFrame)
        case "hideInlineNativePreview":
            if let requestId = dict["requestId"] as? String, !requestId.isEmpty {
                filePreviewCoordinator.hideInlineNativePreview(requestId: requestId)
            }
        case "clearInlineNativePreview":
            if let requestId = dict["requestId"] as? String, !requestId.isEmpty {
                filePreviewCoordinator.clearInlineNativePreview(requestId: requestId)
            }
        case "openFile", "openContainingFolder", "openFilePreviewWindow", "openLocalWebPreview", "checkFilePreviewAvailability":
            _ = handleOpenFilePreviewBridgeMessage(type: type, dict: dict)
        default:
            DevLogger.shared.info("[BasilBoardWebView] Unknown bridge type: \(type)", context: "BasilBoard")
        }
    }

    func sendInitWhenPortReady(attempt: Int = 0) {
        let port = APIClient.shared.currentPort
        guard port > 0 else {
            guard attempt < 30 else {
                DevLogger.shared.error("[BasilBoardWebView] API port unavailable", context: "BasilBoard")
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                self?.sendInitWhenPortReady(attempt: attempt + 1)
            }
            return
        }
        sendInit(port: port)
    }

    func sendInit(port: Int) {
        var payload: [String: Any] = [
            "apiBaseUrl": "http://127.0.0.1:\(port)",
            "theme": AestheticWebPayload.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
        ]
        if let initialConversationId {
            payload["initialConversationId"] = initialConversationId
        }
        payload["conversationPresentation"] = conversationPresentation.rawValue
        if let detachedTabId {
            payload["detachedTabId"] = detachedTabId
        }
        emitBridgeCallback("onInit", payload: payload)
        bridgeInitialized = true
        emitBridgeCallback(
            "onDetachedBoardTabsChanged",
            payload: ["detachedTabIds": detachedTabIds]
        )
        emitBridgeCallback(
            "onDetachedConversationsChanged",
            payload: ["conversationIds": detachedConversationIds]
        )
        if let navigation = pendingAgentTaskOriginNavigation {
            pendingAgentTaskOriginNavigation = nil
            emitBridgeCallback(
                "onNavigateToAgentTaskOrigin",
                payload: ["originType": navigation.originType, "originId": navigation.originId]
            )
        }
        if pendingConversationComposerFocus {
            pendingConversationComposerFocus = false
            emitBridgeCallback("onFocusConversationComposer", payload: [:])
        }
        emitCurrentStatusIcon()
    }

    func setDetachedTabIds(_ tabIds: [String]) {
        detachedTabIds = tabIds
        if bridgeInitialized {
            emitBridgeCallback("onDetachedBoardTabsChanged", payload: ["detachedTabIds": tabIds])
        }
    }

    func setDetachedConversationIds(_ conversationIds: [String]) {
        detachedConversationIds = conversationIds
        if bridgeInitialized {
            emitBridgeCallback("onDetachedConversationsChanged", payload: ["conversationIds": conversationIds])
        }
    }

    func updateDetachedConversationIds(_ ids: [String]) {
        setDetachedConversationIds(ids)
    }

    @discardableResult
    func navigateToAgentTaskOrigin(originType: String, originId: String) -> Bool {
        let allowedOriginTypes: Set<String> = ["todo", "todo_workspace", "scheduled_task", "meeting", "conversation"]
        guard allowedOriginTypes.contains(originType), !originId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            DevLogger.shared.error("[BasilBoardWebView] Rejected invalid Agent Task origin navigation", context: "BasilBoard")
            return false
        }
        if bridgeInitialized {
            emitBridgeCallback(
                "onNavigateToAgentTaskOrigin",
                payload: ["originType": originType, "originId": originId]
            )
        } else {
            pendingAgentTaskOriginNavigation = (originType, originId)
        }
        return true
    }

    /// Makes the web view first responder and asks the page to focus the conversation composer, deferring the page request until the bridge is initialized.
    func focusConversationComposer() {
        hostWindow?.makeFirstResponder(webView)
        if bridgeInitialized {
            emitBridgeCallback("onFocusConversationComposer", payload: [:])
        } else {
            pendingConversationComposerFocus = true
        }
    }

    /// Releases the embedded Agent Tasks surface before this native Board host
    /// is discarded. WebKit does not guarantee React's effect cleanup runs
    /// when its enclosing `WKWebView` is removed, so native window dismissal
    /// must perform the same state transition explicitly.
    func tearDown() {
        filePreviewCoordinator.tearDown()
        DetachedConversationThreadWindowManager.shared.removeObserver(self)
        deactivateBoardAgentTasksSurface()
        deactivateBoardConversationSurface()
        deactivateBoardMeetingsSurface()
    }

    func emitThemeChanged() {
        let payload: [String: Any] = [
            "theme": AestheticWebPayload.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
        ]
        emitBridgeCallback("onThemeChanged", payload: payload)
    }

    func emitBridgeCallback(_ callback: String, payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        webView.evaluateJavaScript("window.basilBoardBridge && window.basilBoardBridge.\(callback) && window.basilBoardBridge.\(callback)(\(json));")
    }

    private func emitCurrentStatusIcon() {
        guard let appDelegate = NSApp.delegate as? AppDelegate,
              let iconName = appDelegate.statusBarManager?.statusBarItem.currentIconResourceName(),
              let image = NSImage(named: NSImage.Name(iconName)),
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            return
        }
        emitBridgeCallback(
            "onStatusIconChanged",
            payload: ["dataUrl": "data:image/png;base64,\(png.base64EncodedString())"]
        )
    }

    private func emitVoiceCaptureState(
        _ state: String,
        surface: BasilBoardVoiceCaptureSurface,
        level: Float? = nil,
        error: String? = nil
    ) {
        var payload: [String: Any] = ["state": state]
        if let level { payload["level"] = level }
        if let error { payload["error"] = error }
        emitBridgeCallback(surface.stateCallback, payload: payload)
    }

    private func emitVoiceCaptureFinished(
        surface: BasilBoardVoiceCaptureSurface,
        transcription: String? = nil,
        error: String? = nil
    ) {
        var payload: [String: Any] = [:]
        if let transcription { payload["transcription"] = transcription }
        if let error { payload["error"] = error }
        emitBridgeCallback(surface.finishedCallback, payload: payload)
    }

    private func emitWidgetLaunchFailed(reason: String, message: String) {
        emitBridgeCallback("onWidgetLaunchFailed", payload: ["reason": reason, "message": message])
    }

    /// The Board's own top and left chrome (header/bubble, tab rail) is laid
    /// out in CSS *inside* `.basil-webkit-window-frame`'s
    /// `--basil-webkit-window-frame-inset` (4px) padding -- see
    /// `webkit-window-chrome.css`. An embedded native host is a separate
    /// `NSView` layered on top of that CSS layout via Auto Layout
    /// constraints relative to `hostView` (the raw `WKWebView`, whose bounds
    /// start *before* that 4px CSS inset), so every inset below adds that
    /// 4px on top of the plain CSS box size or it will encroach 4px into
    /// whatever the Board renders there (the tab rail's right border, or the
    /// header/bubble's bottom edge).
    ///
    /// Top: on the main (non-detached) window, `.basil-board-header` is
    /// 44px tall with `padding-top: 8px`, and its 44px-tall bubble is
    /// `align-items: flex-start` inside that padding, so the bubble's true
    /// bottom edge is 4 (frame) + 8 (header padding-top) + 44 (bubble) = 56,
    /// 8px below the header's own 44px box -- an intentional bleed that
    /// only DOM content (which respects CSS stacking) can sit under. A
    /// native host cannot participate in that stacking, so it must start
    /// below the bubble's true bottom edge instead of the header's nominal
    /// box. On a detached window there's no bubble, just
    /// `.basil-board-detached-header`'s plain 44px box, so 4 (frame) + 44 =
    /// 48 is enough.
    ///
    /// Leading: `.basil-board-tabs` (the tab rail) is 52px wide with a
    /// `border-right`, only present on the main window, so its true right
    /// edge is 4 (frame) + 52 (rail) = 56. Detached windows have no rail, so
    /// only the bare 4px frame inset applies.
    ///
    /// Hand-computed CSS math above is a *fallback only*. It has twice
    /// proven insufficient to exactly match the drawn tab-rail border and
    /// header bubble bottom edge (subpixel/box-model details a static
    /// constant can't capture). `BoardChrome.tsx` measures its own rendered
    /// `.basil-board-tabs` and `.basil-board-bubble` geometry via
    /// `getBoundingClientRect()` and reports it through
    /// `reportBoardChromeGeometry`, which is authoritative once received
    /// (`measuredContentLeft`/`measuredContentTop` below). Because
    /// `BoardChrome` always mounts before any tab is switched to, this
    /// measurement is in hand well before Meetings/Agent Tasks activate
    /// their embedded host on the main window.
    private var measuredContentLeft: CGFloat?
    private var measuredContentTop: CGFloat?
    private var embeddedTopInset: CGFloat { measuredContentTop ?? (detachedTabId == nil ? 56 : 48) }
    private var embeddedLeadingInset: CGFloat { measuredContentLeft ?? (detachedTabId == nil ? 56 : 4) }

    /// Reconciles the embedded webview's existence with the coordinator's
    /// current authority and pushes the resulting availability to the web
    /// layer. Called on every coordinator state change while this Board's
    /// Agent Tasks tab is mounted (`activateBoardAgentTasksSurface`..
    /// `deactivateBoardAgentTasksSurface`).
    private func reconcileAgentTasksEmbedding() {
        let standaloneAuthoritative = AgentTaskResultPresentationCoordinator.shared.isStandaloneVisible
        if standaloneAuthoritative {
            tearDownAgentTasksEmbedding()
        } else if agentTaskResultEmbeddedHost == nil {
            let host = AgentTaskResultEmbeddedHost(
                embeddingInto: webView,
                topInset: embeddedTopInset,
                leadingInset: embeddedLeadingInset,
                originatingWindow: hostWindow
            )
            host.onStartNewAgentTaskCapture = { preGeneratedId in
                if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                    appDelegate.statusBarManager?.windowCoordinator.showAgentTaskCaptureWidget(
                        preGeneratedAgentTaskId: preGeneratedId
                    )
                }
            }
            agentTaskResultEmbeddedHost = host
        }
        emitBridgeCallback(
            "onBoardAgentTasksAvailabilityChanged",
            payload: ["availability": standaloneAuthoritative ? "separate_window" : "embedded"]
        )
    }

    private func tearDownAgentTasksEmbedding() {
        agentTaskResultEmbeddedHost?.tearDown()
        agentTaskResultEmbeddedHost = nil
    }

    private func deactivateBoardAgentTasksSurface() {
        AgentTaskResultPresentationCoordinator.shared.removeObserver(id: presentationObserverID)
        guard isAgentTasksSurfaceActive else {
            tearDownAgentTasksEmbedding()
            return
        }
        isAgentTasksSurfaceActive = false
        AgentTaskResultPresentationCoordinator.shared.unregisterBoardVisible()
        tearDownAgentTasksEmbedding()
    }

    private func emitBoardConversationAvailability() {
        let available = !ConversationPresentationCoordinator.shared.isStandaloneVisible
        emitBridgeCallback(
            "onBoardConversationAvailabilityChanged",
            payload: ["availability": available ? "available" : "unavailable"]
        )
    }

    private func deactivateBoardConversationSurface() {
        ConversationPresentationCoordinator.shared.removeObserver(id: conversationPresentationObserverID)
        guard isConversationSurfaceActive else { return }
        isConversationSurfaceActive = false
        ConversationPresentationCoordinator.shared.unregisterBoardVisible()
    }

    /// Reconciles the embedded Meeting Assistant host against the standalone
    /// window's current authority and pushes the resulting availability to
    /// the web layer. Called on every coordinator state change while this
    /// Board's Meetings tab is mounted (`activateBoardMeetingsSurface`..
    /// `deactivateBoardMeetingsSurface`). Mirrors
    /// `reconcileAgentTasksEmbedding()` exactly.
    private func reconcileMeetingsEmbedding() {
        let standaloneAuthoritative = MeetingPresentationCoordinator.shared.isStandaloneVisible
        if standaloneAuthoritative {
            tearDownMeetingsEmbedding()
        } else if meetingAssistantEmbeddedHost == nil {
            guard let coordinator = meetingSessionCoordinatorProvider() else {
                DevLogger.shared.error(
                    "[BasilBoardWebView] No MeetingSessionCoordinator available for Meetings embedding",
                    context: "BasilBoard"
                )
                return
            }
            meetingAssistantEmbeddedHost = MeetingAssistantEmbeddedHost(
                embeddingInto: webView,
                topInset: embeddedTopInset,
                leadingInset: embeddedLeadingInset,
                coordinator: coordinator
            )
        }
        emitBridgeCallback(
            "onBoardMeetingsAvailabilityChanged",
            payload: ["availability": standaloneAuthoritative ? "separate_window" : "embedded"]
        )
    }

    private func tearDownMeetingsEmbedding() {
        meetingAssistantEmbeddedHost?.tearDown()
        meetingAssistantEmbeddedHost = nil
    }

    private func deactivateBoardMeetingsSurface() {
        MeetingPresentationCoordinator.shared.removeObserver(id: meetingsPresentationObserverID)
        guard isMeetingsSurfaceActive else {
            tearDownMeetingsEmbedding()
            return
        }
        isMeetingsSurfaceActive = false
        MeetingPresentationCoordinator.shared.unregisterBoardVisible()
        tearDownMeetingsEmbedding()
    }

    private func saveConversationPastedImages(_ rawDataUrls: Any?) {
        guard let dataUrls = rawDataUrls as? [String],
              !dataUrls.isEmpty,
              dataUrls.count <= maximumPastedImageCount else {
            emitBridgeCallback(
                "onConversationAttachmentError",
                payload: ["message": "Paste at most \(maximumPastedImageCount) images at once."]
            )
            return
        }

        do {
            let imageData = try dataUrls.map { dataUrl -> Data in
                guard let commaIndex = dataUrl.firstIndex(of: ","),
                      dataUrl[..<commaIndex].contains(";base64"),
                      let decoded = Data(base64Encoded: String(dataUrl[dataUrl.index(after: commaIndex)...])),
                      !decoded.isEmpty else {
                    throw ConversationPastedImageAttachmentWriter.PasteImageError.invalidImageData
                }
                guard decoded.count <= maximumPastedImageBytes else {
                    throw NSError(
                        domain: "BasilBoard",
                        code: 413,
                        userInfo: [NSLocalizedDescriptionKey: "Each pasted image must be 20 MiB or smaller."]
                    )
                }
                return decoded
            }
            let urls = try ConversationPastedImageAttachmentWriter.writePastedImageData(imageData)
            emitBridgeCallback(
                "onConversationFilesPicked",
                payload: ["paths": urls.map(\.path)]
            )
        } catch {
            emitBridgeCallback(
                "onConversationAttachmentError",
                payload: ["message": error.localizedDescription]
            )
        }
    }

    private func startVoiceCapture(surface: BasilBoardVoiceCaptureSurface) {
        guard activeVoiceCaptureSurface == nil else {
            emitVoiceCaptureState(
                "error",
                surface: surface,
                error: "Another BasilBoard voice capture is already active."
            )
            emitVoiceCaptureFinished(
                surface: surface,
                error: "capture_already_active"
            )
            return
        }

        activeVoiceCaptureSurface = surface
        voiceCaptureTask?.cancel()
        emitVoiceCaptureState("starting", surface: surface)
        voiceCaptureTask = Task { @MainActor in
            do {
                try await audioCaptureService.startRecording(flowContext: surface.flowContext)
                guard activeVoiceCaptureSurface == surface else { return }
                emitVoiceCaptureState("recording", surface: surface)
            } catch {
                guard !Task.isCancelled, activeVoiceCaptureSurface == surface else { return }
                activeVoiceCaptureSurface = nil
                emitVoiceCaptureState("error", surface: surface, error: error.localizedDescription)
                emitVoiceCaptureFinished(surface: surface, error: error.localizedDescription)
            }
        }
    }

    private func finishVoiceCapture(
        surface: BasilBoardVoiceCaptureSurface,
        canceled: Bool
    ) {
        guard activeVoiceCaptureSurface == surface else { return }
        voiceCaptureTask?.cancel()
        voiceCaptureTask = Task { @MainActor in
            audioCaptureService.stopRecording(
                sendAudioData: false,
                flowContext: surface.flowContext
            )
            if canceled {
                audioCaptureService.clearRecordingData()
                activeVoiceCaptureSurface = nil
                emitVoiceCaptureState("idle", surface: surface)
                emitVoiceCaptureFinished(surface: surface, error: "canceled")
                return
            }

            emitVoiceCaptureState("processing", surface: surface)
            guard let audioData = audioCaptureService.lastRecordingData,
                  !audioData.isEmpty else {
                activeVoiceCaptureSurface = nil
                emitVoiceCaptureState("error", surface: surface, error: "No audio captured")
                emitVoiceCaptureFinished(surface: surface, error: "no_audio")
                return
            }
            audioCaptureService.clearRecordingData()

            do {
                let transcription = try await uploadVoiceTranscription(
                    audioData: audioData,
                    surface: surface
                )
                activeVoiceCaptureSurface = nil
                emitVoiceCaptureState("idle", surface: surface)
                emitVoiceCaptureFinished(surface: surface, transcription: transcription)
            } catch {
                activeVoiceCaptureSurface = nil
                emitVoiceCaptureState("error", surface: surface, error: error.localizedDescription)
                emitVoiceCaptureFinished(surface: surface, error: error.localizedDescription)
            }
        }
    }

    private func uploadVoiceTranscription(
        audioData: Data,
        surface: BasilBoardVoiceCaptureSurface
    ) async throws -> String {
        let apiBase = APIClient.shared.baseURL
        guard let url = URL(string: "\(apiBase)\(surface.transcribePath)") else {
            throw NSError(domain: "BasilBoard", code: 400, userInfo: [NSLocalizedDescriptionKey: "Invalid transcribe URL"])
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"\(surface.audioFilename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw NSError(domain: "BasilBoard", code: (response as? HTTPURLResponse)?.statusCode ?? 500, userInfo: [NSLocalizedDescriptionKey: "Transcription upload failed"])
        }
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "BasilBoard", code: 500, userInfo: [NSLocalizedDescriptionKey: "Invalid transcription response"])
        }
        let success = (json["success"] as? Bool) ?? false
        let transcription = (json["transcription"] as? String) ?? ""
        if !success || transcription.isEmpty {
            let errorCode = (json["error_code"] as? String) ?? "transcription_failed"
            throw NSError(domain: "BasilBoard", code: 422, userInfo: [NSLocalizedDescriptionKey: errorCode])
        }
        return transcription
    }
}
