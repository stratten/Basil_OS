import AppKit
import Foundation

/// Lightweight description of a meeting the backend mechanical loop detected,
/// decoded from the `meeting_detected` WS payload.
struct DetectedMeetingInfo: Equatable {
    let appName: String
    let bundleID: String
    let pid: Int32?
    let mode: String          // "prompt" | "auto_start"
    let calendarTitle: String?
    let calendarName: String?
    let calendarAttendees: [String]
    let calendarJoinURL: URL?
    let calendarHasCallInfo: Bool
    let calendarEventID: String?
    /// Cleaned window/tab title captured by the probe (already run through
    /// `MeetingWindowTitleCleaner` on the client-side probe, so this is used
    /// as-is). Gives audio-only detections with no calendar match a more
    /// specific `displayTitle` than the bare app name, e.g. "Google Meet"
    /// instead of "Microsoft Edge" for an ad-hoc browser call.
    let windowTitle: String?

    /// Best title for the meeting: the calendar event if enrichment provided
    /// one, otherwise the cleaned window/tab title if the probe captured
    /// one, otherwise the app name.
    var displayTitle: String {
        if let title = calendarTitle, !title.isEmpty { return title }
        if let title = windowTitle, !title.isEmpty { return title }
        return appName
    }

    var canJoinMeeting: Bool { calendarJoinURL != nil }

    init?(json: [String: Any]) {
        guard let meeting = json["meeting"] as? [String: Any] else { return nil }
        guard let appName = meeting["app_name"] as? String else { return nil }
        self.appName = appName
        self.bundleID = meeting["bundle_id"] as? String ?? ""
        if let pid = meeting["pid"] as? Int { self.pid = Int32(pid) } else { self.pid = nil }
        self.mode = meeting["mode"] as? String ?? "prompt"
        let title = meeting["calendar_title"] as? String
        self.calendarTitle = (title?.isEmpty == false) ? title : nil
        let calendarName = meeting["calendar_name"] as? String
        self.calendarName = (calendarName?.isEmpty == false) ? calendarName : nil
        self.calendarAttendees = meeting["calendar_attendees"] as? [String] ?? []
        if let joinURLString = meeting["calendar_join_url"] as? String {
            self.calendarJoinURL = URL(string: joinURLString)
        } else {
            self.calendarJoinURL = nil
        }
        self.calendarHasCallInfo = meeting["calendar_has_call_info"] as? Bool ?? false
        let eventID = meeting["calendar_event_id"] as? String
        self.calendarEventID = (eventID?.isEmpty == false) ? eventID : nil
        let windowTitleValue = meeting["window_title"] as? String
        self.windowTitle = (windowTitleValue?.isEmpty == false) ? windowTitleValue : nil
    }
}

/// Floating WKWebView mini panel that surfaces a detected meeting and offers to
/// start transcription. Modeled directly on ``ScheduledRunMiniPanelWindowController``:
/// AppKit owns the transparent non-activating host window, while the web layer
/// owns the rendered chrome so the prompt can later move to other shells.
@MainActor
final class MeetingDetectedMiniPanelWindowController: NSObject, NSWindowDelegate, AppearanceRefreshable {
    private var panel: NSPanel?
    private var webViewHost: MeetingDetectedMiniPanelWebView?
    private var currentMeeting: DetectedMeetingInfo?

    /// Invoked when the user clicks "Start transcription". The AppDelegate wires
    /// this through to the armed live-transcription start.
    var onStart: ((DetectedMeetingInfo) -> Void)?
    var onDismissMeeting: ((DetectedMeetingInfo) -> Void)?

    // Initial size before the React layer's content-driven `requestResize`
    // call arrives (which measures actual rendered content, since the
    // attendee chip row can wrap to a variable number of lines). Kept in
    // sync with MeetingDetectedMiniPanel/src/App.tsx's PANEL_WIDTH; height
    // is a reasonable starting guess for the common one-detail-row case and
    // gets corrected immediately once real content is measured.
    private let contentSize = NSSize(width: 340, height: 132)
    private let chromeInset = WebKitWindowChromeAppearance.frameInset

    private var panelSize: NSSize {
        NSSize(
            width: contentSize.width + chromeInset * 2,
            height: contentSize.height + chromeInset * 2
        )
    }

    var isVisible: Bool { panel?.isVisible ?? false }

    // MARK: - Public API

    /// Show the panel for a freshly detected meeting (or update it in place if
    /// already visible).
    func present(meeting: DetectedMeetingInfo) {
        currentMeeting = meeting

        if panel == nil { createPanel() }
        guard let panel = panel else { return }
        webViewHost?.sendMeeting(meeting)

        if !panel.isVisible {
            positionBottomRight(panel)
            panel.alphaValue = 0
            panel.orderFront(nil)
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.18
                panel.animator().alphaValue = 1
            }
        }
    }

    func hide(immediate: Bool = false) {
        guard let panel = panel else { return }
        if immediate {
            panel.alphaValue = 0
            panel.orderOut(nil)
            return
        }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.18
            panel.animator().alphaValue = 0
        }, completionHandler: {
            panel.orderOut(nil)
        })
    }

    /// Hide the panel because a recording actively started elsewhere (any
    /// meeting, not necessarily the one this prompt is for). Unlike a manual
    /// dismiss, this does not suppress the calendar event: starting a different
    /// recording says nothing about whether the user still wants to be prompted
    /// for this meeting later.
    func hideForActiveRecording() {
        guard isVisible else { return }
        hide()
    }

    /// Hide the panel because the backend determined the calendar event backing
    /// the current prompt has ended with no user action taken. The backend has
    /// already suppressed the event server-side (added to its ignored set), so
    /// unlike a manual dismiss this does not call `onDismissMeeting` again -- it
    /// only needs to update what's on screen, and only if it's still showing the
    /// meeting the expired event_id refers to.
    func hideForExpiredCalendarEvent(eventID: String) {
        guard let meeting = currentMeeting, meeting.calendarEventID == eventID else { return }
        hide(immediate: true)
    }

    // MARK: - Private

    private func createPanel() {
        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: panelSize),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        panel.title = "Meeting Detected"
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.worksWhenModal = true
        panel.hasShadow = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.isMovableByWindowBackground = true
        panel.delegate = self

        let host = MeetingDetectedMiniPanelWebView()
        self.webViewHost = host

        host.onStartMeeting = { [weak self] in
            guard let self, let meeting = self.currentMeeting else { return }
            // Order out before launch side effects so the prompt cannot linger
            // over the browser/live-transcription activation path.
            self.hide(immediate: true)
            self.onStart?(meeting)
        }
        host.onDismissMeeting = { [weak self] in
            guard let self else { return }
            let meeting = self.currentMeeting
            self.hide(immediate: true)
            if let meeting {
                self.onDismissMeeting?(meeting)
            }
        }
        host.onRequestResize = { [weak self] width, height in
            self?.resize(to: NSSize(width: width, height: height))
        }

        panel.contentView = host.webView
        WebKitWindowChromeAppearance.apply(to: panel)
        host.installDragArea()

        positionBottomRight(panel)
        self.panel = panel
        AppearanceRefreshCoordinator.shared.register(self)
        host.loadContent()
    }

    func refreshAppearance() {
        webViewHost?.sendThemeChanged()
    }

    deinit {
        MainActor.assumeIsolated {
            AppearanceRefreshCoordinator.shared.unregister(self)
        }
    }

    private func positionBottomRight(_ panel: NSPanel) {
        let mouseLocation = NSEvent.mouseLocation
        let targetScreen = NSScreen.screens.first { NSMouseInRect(mouseLocation, $0.frame, false) } ?? NSScreen.main
        guard let screen = targetScreen else {
            panel.center()
            return
        }
        let visibleFrame = screen.visibleFrame
        let panelSize = panel.frame.size
        let padding: CGFloat = 16
        let originX = visibleFrame.maxX - panelSize.width - padding
        let originY = visibleFrame.origin.y + padding
        panel.setFrameOrigin(NSPoint(x: originX, y: originY))
    }

    private func resize(to newSize: NSSize) {
        guard let panel = panel else { return }
        let currentFrame = panel.frame
        let paddedSize = NSSize(
            width: newSize.width + chromeInset * 2,
            height: newSize.height + chromeInset * 2
        )
        let newOriginY = currentFrame.origin.y
        let newOriginX = currentFrame.origin.x + (currentFrame.width - paddedSize.width)
        let newFrame = NSRect(origin: NSPoint(x: newOriginX, y: newOriginY), size: paddedSize)
        if panel.isVisible {
            panel.setFrame(newFrame, display: true, animate: true)
        } else {
            panel.setFrame(newFrame, display: false)
        }
    }

    // MARK: - NSWindowDelegate

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hide()
        return false
    }
}
