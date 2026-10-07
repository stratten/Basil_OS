import AppKit
import Foundation
import UniformTypeIdentifiers

/// WebKit host for analysis results, suggested-action review, retry, copy,
/// and export. Uses native `NSSavePanel` only for the user-chosen export
/// destination; every other action routes through the coordinator's typed
/// intent handler.
@MainActor
final class MeetingAnalysisWebWindowController: NSObject, NSWindowDelegate {
    private let coordinator: MeetingSessionCoordinator
    private var window: NSWindow?
    private var meetingWebView: MeetingAssistantWebView?
    private var presentationToken: MeetingPresentationToken?
    private var pendingResult: MeetingAnalysisResultDTO?
    private var collapseController: WindowCollapseController?

    var onClosed: (() -> Void)?

    init(coordinator: MeetingSessionCoordinator) {
        self.coordinator = coordinator
        super.init()
    }

    func show(result: MeetingAnalysisResultDTO?) {
        pendingResult = result
        if let window {
            if window.isMiniaturized {
                window.deminiaturize(nil)
            }
            window.makeKeyAndOrderFront(nil)
            window.orderFrontRegardless()
            return
        }

        let window = ClosableBorderlessPanel(
            contentRect: NSRect(x: 0, y: 0, width: 600, height: 700),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Meeting Analysis"
        window.minSize = NSSize(width: 520, height: 420)
        window.level = .floating
        window.hidesOnDeactivate = false
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.isMovableByWindowBackground = true
        window.delegate = self

        let meetingWebView = MeetingAssistantWebView()
        self.meetingWebView = meetingWebView
        // Trailing band widened past the shared default to cover this
        // window's "Copy All" + "Export" text buttons (`.meeting-window-chrome-trailing`
        // in `MeetingAnalysisApp.tsx`), which run wider than the plain
        // recording bubble the main Meeting Assistant window's default covers.
        meetingWebView.installDragArea(trailingInteractiveWidth: 220)
        meetingWebView.onClose = { [weak self] in self?.window?.close() }
        meetingWebView.onMinimize = { [weak self] in self?.window?.miniaturize(nil) }
        meetingWebView.onToggleCollapse = { [weak self] collapsed in self?.applyCollapse(collapsed) }

        let token = coordinator.attachWebPresentation(
            sink: { [weak meetingWebView] event in
                meetingWebView?.send(event)
            },
            meterSink: { [weak meetingWebView] payload in
                meetingWebView?.publishMeter(payload)
            }
        )
        presentationToken = token
        meetingWebView.onIntent = { [weak self] intent, payload in
            guard let self else { return }
            if intent == .reactReady {
                self.coordinator.webPresentationDidBecomeReady(token)
            } else {
                self.handle(intent, payload: payload)
            }
        }

        window.contentView = meetingWebView.webView
        WebKitWindowChromeAppearance.apply(to: window)
        window.center()
        self.window = window
        collapseController = WindowCollapseController(
            window: window,
            compactSize: NSSize(width: 280, height: 64),
            fallbackExpandedSize: NSSize(width: 600, height: 700)
        )

        meetingWebView.loadContent(entryFile: "src/entries/meeting-analysis.html")
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
    }

    func showLoading() {
        show(result: nil)
    }

    /// Analysis-specific intents this window answers directly (export via
    /// native save panel, copy via `NSPasteboard`) rather than forwarding to
    /// the coordinator, since they have no effect on the shared recording
    /// session. Every other intent (`retryAnalysisModes`, proposal outcomes)
    /// still forwards to the coordinator so the underlying model/store stay
    /// the single source of truth.
    private func handle(_ intent: MeetingBridgeIntent, payload: [String: Any]) {
        switch intent {
        case .copyText:
            guard let text = payload["text"] as? String else { return }
            let rich = payload["rich"] as? Bool ?? false
            NSPasteboard.general.clearContents()
            if rich {
                let attributed = MarkdownUtils.markdownToAttributedString(text)
                NSPasteboard.general.setString(attributed.string, forType: .string)
                if MarkdownUtils.containsMarkdown(text),
                   let rtfData = attributed.rtf(from: NSRange(location: 0, length: attributed.length), documentAttributes: [:]) {
                    NSPasteboard.general.setData(rtfData, forType: .rtf)
                }
            } else {
                NSPasteboard.general.setString(text, forType: .string)
            }
        case .exportAnalysis:
            let text: String
            let filenameSuggestion: String
            if let payloadText = payload["text"] as? String {
                text = payloadText
                filenameSuggestion = payload["filenameSuggestion"] as? String ?? "meeting-analysis.md"
            } else if let pendingResult {
                text = Self.exportMarkdown(from: pendingResult)
                filenameSuggestion = "\(pendingResult.meetingName ?? "meeting")-analysis.md"
            } else {
                return
            }
            let panel = NSSavePanel()
            panel.applyBasilThemedAppearance()
            panel.allowedContentTypes = [UTType(filenameExtension: "md") ?? .plainText]
            panel.nameFieldStringValue = filenameSuggestion
            panel.begin { [weak self] response in
                guard response == .OK, let url = panel.url else { return }
                do {
                    try text.write(to: url, atomically: true, encoding: .utf8)
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed to export meeting analysis to \(url.path): \(error.localizedDescription)", context: "LiveTranscription")
                    #endif
                }
                self?.coordinator.handleWebIntent(.exportAnalysis, payload: ["exported": true])
            }
        default:
            coordinator.handleWebIntent(intent, payload: payload)
        }
    }

    private func applyCollapse(_ collapsed: Bool) {
        meetingWebView?.installDragArea(trailingInteractiveWidth: collapsed ? 0 : 220)
        collapseController?.setCollapsed(collapsed)
    }

    func windowWillClose(_ notification: Notification) {
        if let presentationToken {
            coordinator.detachPresentation(presentationToken)
        }
        presentationToken = nil
        meetingWebView?.tearDown()
        meetingWebView = nil
        collapseController = nil
        window = nil
        onClosed?()
    }

    private static func exportMarkdown(from result: MeetingAnalysisResultDTO) -> String {
        var parts: [String] = [
            "# \(result.meetingName ?? "Meeting Analysis")",
            "*Analyzed: \(result.analyzedAt)*",
            "*Model: \(result.modelUsed)*",
        ]
        if let summary = result.summary {
            parts.append("## Summary")
            parts.append(summary)
        }
        if let actionItems = result.actionItems, !actionItems.isEmpty {
            parts.append("## Action Items")
            parts.append(contentsOf: actionItems.map { "- \($0.task)" })
        }
        if let decisions = result.decisions, !decisions.isEmpty {
            parts.append("## Key Decisions")
            parts.append(contentsOf: decisions.map { "- \($0.decision)" })
        }
        if let customAnalysis = result.customAnalysis {
            parts.append("## Custom Analysis")
            parts.append(customAnalysis)
        }
        if let transcript = result.transcript, !transcript.isEmpty {
            parts.append("## Transcript")
            parts.append(formatTranscriptForExport(transcript))
        }
        return parts.joined(separator: "\n\n")
    }

    /// Native mirror of the web bundle's `formatTranscriptForCopy`: one
    /// `[timestamp] Speaker` header per turn with its line(s) indented
    /// beneath, separated by a blank line between speaker swaps. Kept in
    /// sync with `web-components/MeetingAssistant/src/lib/transcriptFormatting.ts`
    /// since this native fallback only runs when the web bundle failed to
    /// supply pre-built export text.
    private static func formatTranscriptForExport(_ lines: [TranscriptLineDTO]) -> String {
        var blocks: [String] = []
        var currentHeader: String?
        var currentLines: [String] = []
        var previousGroupKey: String?

        func flush() {
            guard let header = currentHeader, !currentLines.isEmpty else { return }
            let indented = currentLines.map { "    \($0)" }
            blocks.append(([header] + indented).joined(separator: "\n"))
        }

        for line in lines {
            let text = line.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { continue }
            let groupKey = "\(line.source ?? "")|\(line.speakerId ?? "")"
            if groupKey != previousGroupKey || currentHeader == nil {
                flush()
                let timestamp = formatTranscriptTimestamp(line.displayStart)
                let label = transcriptSpeakerLabel(source: line.source, speakerId: line.speakerId)
                currentHeader = label.map { "\(timestamp) \($0)" } ?? timestamp
                currentLines = [text]
            } else {
                currentLines.append(text)
            }
            previousGroupKey = groupKey
        }
        flush()
        return blocks.joined(separator: "\n\n")
    }

    private static func formatTranscriptTimestamp(_ value: String?) -> String {
        guard let value else { return "[00:00]" }
        let parts = value.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 3 else { return "[\(value)]" }
        let (hours, minutes, seconds) = (parts[0], parts[1], parts[2])
        if hours > 0 {
            return String(format: "[%d:%02d:%02d]", hours, minutes, seconds)
        }
        return String(format: "[%02d:%02d]", minutes, seconds)
    }

    private static func transcriptSpeakerLabel(source: String?, speakerId: String?) -> String? {
        if let source {
            return source == "Microphone" ? "Microphone" : "System Audio"
        }
        guard let speakerId, let match = speakerId.range(of: #"\d+$"#, options: .regularExpression) else {
            return nil
        }
        guard let number = Int(speakerId[match]) else { return nil }
        let isSpeakerPrefixed = speakerId.lowercased().hasPrefix("speaker")
        let displayNumber = isSpeakerPrefixed ? number + 1 : number
        guard displayNumber > 0 else { return nil }
        return "Speaker \(displayNumber)"
    }
}
