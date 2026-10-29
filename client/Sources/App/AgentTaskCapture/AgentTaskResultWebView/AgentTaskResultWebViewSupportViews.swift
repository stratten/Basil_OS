import AppKit
@preconcurrency import WebKit

func performAgentTaskRESTCancellation(
    agentTaskId: String,
    cancel: ((String) async throws -> Void)? = nil
) async throws {
    if let cancel {
        try await cancel(agentTaskId)
        return
    }
    _ = try await APIClient.shared.cancelAgentTaskSession(
        agentTaskId: agentTaskId,
        reason: "User requested cancellation"
    )
}

func decodeAgentTaskCancellationIdentifier(from body: Any) -> String? {
    guard let message = body as? [String: Any],
          message["type"] as? String == "cancelRunningAgentTask",
          let agentTaskId = message["agentTaskId"] as? String,
          !agentTaskId.isEmpty else {
        return nil
    }
    return agentTaskId
}

/// Transparent overlay that sits on top of the WKWebView header area to enable
/// window dragging. WKWebView's internal subviews consume mouse events before
/// a WKWebView subclass override can intercept them, so we use an overlay instead.
/// Returns nil from hitTest for button/bubble areas to let clicks pass through.
class WindowDragAreaView: NSView {
    private let leadingInteractiveWidth: CGFloat
    private let trailingInteractiveWidth: CGFloat

    init(leadingInteractiveWidth: CGFloat = 120, trailingInteractiveWidth: CGFloat = 136) {
        self.leadingInteractiveWidth = leadingInteractiveWidth
        self.trailingInteractiveWidth = trailingInteractiveWidth
        super.init(frame: .zero)
    }

    required init?(coder: NSCoder) {
        self.leadingInteractiveWidth = 120
        self.trailingInteractiveWidth = 136
        super.init(coder: coder)
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    
    override func hitTest(_ point: NSPoint) -> NSView? {
        let local = point
        guard bounds.contains(local) else { return nil }
        if local.x < leadingInteractiveWidth || local.x >= bounds.width - trailingInteractiveWidth {
            return nil
        }
        return self
    }
    
    override func mouseDown(with event: NSEvent) {
        window?.makeKey()
        window?.performDrag(with: event)
    }
}

/// WKWebView subclass that accepts first-mouse clicks so the user doesn't have
/// to click twice (once to focus, once to interact) when the web view is inactive.
class FirstClickWebView: WKWebView {
    override init(frame frameRect: NSRect, configuration: WKWebViewConfiguration) {
        PlainTextPasteWebSupport.install(in: configuration.userContentController)
        let themeBootstrapScript = AestheticWebPayload.documentStartThemeBootstrapScript()
        if !themeBootstrapScript.isEmpty {
            configuration.userContentController.addUserScript(
                WKUserScript(
                    source: themeBootstrapScript,
                    injectionTime: .atDocumentStart,
                    forMainFrameOnly: true
                )
            )
        }
        super.init(frame: frameRect, configuration: configuration)
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseDown(with event: NSEvent) {
        window?.makeKey()
        super.mouseDown(with: event)
    }

    /// Invoked from ``performDragOperation`` whenever the user drops one or
    /// more files/folders onto the web view. The host (``AgentTaskResultWebView``)
    /// wires this to the JS bridge's ``onFilesPicked`` callback so React
    /// surfaces — ``TextFollowUp`` and the Attached Files editor in
    /// ``ScheduledAgentTaskDetail`` — receive absolute paths.
    ///
    /// This indirection exists because WebKit's HTML5 drop event does NOT
    /// expose absolute paths via ``File.path`` (that's an Electron
    /// extension, not a WKWebView one), so the JS-side handlers were
    /// silently receiving empty path arrays on every drop. Reading the
    /// pasteboard at the AppKit layer is the only way to recover them.
    var onFilesDropped: (([String]) -> Void)?

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let pb = sender.draggingPasteboard
        if pb.types?.contains(.fileURL) == true,
           let urls = pb.readObjects(forClasses: [NSURL.self], options: nil) as? [URL],
           !urls.isEmpty {
            let paths = urls.map { $0.path }
            onFilesDropped?(paths)
            // Intentionally fall through to ``super`` so WebKit still fires
            // a JS ``drop`` event. React's drag-target components rely on
            // that event to clear their "Drop files here" highlight; they
            // harmlessly ignore the (unsupported) ``file.path`` lookup
            // because path delivery now happens through the bridge above.
        }
        return super.performDragOperation(sender)
    }
}

