import AppKit
import WebKit

extension AgentTaskCaptureInputWebView {
    /// Staged-resource loading. Identical mechanism to
    /// `AgentTaskResultWebView.swift`, new identifiers only.
    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskCaptureInputWebView] Could not get bundle resource URL", context: "AgentTaskCapture")
            #endif
            return
        }

        let webAssetsFolder = resourceURL.appendingPathComponent("AgentTaskCaptureInputWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/agent-task-capture-input.html")

        #if DEBUG
        DevLogger.shared.info("[AgentTaskCaptureInputWebView \(instanceId)] Loading HTML from: \(htmlURL.path)", context: "AgentTaskCapture")
        #endif

        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskCaptureInputWebView \(instanceId)] HTML file NOT found at: \(htmlURL.path)", context: "AgentTaskCapture")
            #endif
        }
    }

    /// Top-header drag strip, installed once the page finishes loading. The
    /// shared `WindowDragAreaView` passes the rendered controls through to
    /// React and handles native dragging everywhere else in the header.
    func installDragArea() {
        if let existing = dragAreaView {
            existing.removeFromSuperview()
            dragAreaView = nil
        }

        let topGutter = WebKitWindowChromeAppearance.frameInset
        let headerInnerHeight: CGFloat = 40
        // 44pt, not the button's nominal ~12-28pt footprint, because the
        // tighter 34pt band this widget shipped with left the leading
        // (cancel) button clickable only at the extreme edge in practice —
        // confirmed via manual testing to need this much real-world margin
        // even though the vertical/16px icon layout itself is unchanged.
        let dragView = WindowDragAreaView(
            leadingInteractiveWidth: 44,
            trailingInteractiveWidth: 44
        )
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        let heightConstraint = dragView.heightAnchor.constraint(
            equalToConstant: topGutter + headerInnerHeight
        )
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            heightConstraint,
        ])
        dragAreaView = dragView
        dragAreaHeightConstraint = heightConstraint
    }

    func updateDragAreaHeight(_ height: CGFloat) {
        guard height.isFinite, height > 0, dragAreaHeightConstraint?.constant != height else {
            return
        }
        dragAreaHeightConstraint?.constant = height
    }
}
