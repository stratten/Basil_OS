import AppKit
import Foundation

/// Wires the floating ``MeetingDetectedMiniPanelWindowController`` into the
/// AppDelegate lifecycle.
///
/// Responsibilities:
///   * Lazily create the controller the first time a meeting is detected.
///   * Observe ``NSNotification.Name("BasilMeetingDetectedWSEvent")`` (posted by
///     ``WebSocketService`` for `meeting_detected` / `meeting_ended` /
///     `meeting_prompt_expired`).
///   * On `meeting_detected`: if the backend mode is `auto_start`, skip the
///     panel and arm transcription directly; otherwise show the prompt panel.
///   * The panel's "Start transcription" action routes into the armed
///     live-transcription start.
extension AppDelegate {

    private static let meetingDetectedWSEventName = NSNotification.Name("BasilMeetingDetectedWSEvent")

    @MainActor
    func ensureMeetingDetectedMiniPanelController() -> MeetingDetectedMiniPanelWindowController {
        if let existing = meetingDetectedMiniPanelController {
            return existing
        }
        let controller = MeetingDetectedMiniPanelWindowController()
        controller.onStart = { meeting in
            Task { @MainActor in
                guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
                appDelegate.launchDetectedMeeting(meeting)
            }
        }
        controller.onDismissMeeting = { meeting in
            Task { @MainActor in
                guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
                await appDelegate.suppressDetectedCalendarMeeting(meeting)
            }
        }
        meetingDetectedMiniPanelController = controller
        return controller
    }

    /// Subscribe to meeting-detection WS events. Idempotent. The closure
    /// re-derives the AppDelegate (rather than capturing self) for the same
    /// Sendable reasons documented in the scheduled-run observer.
    @MainActor
    func registerMeetingDetectedMiniPanelObserver() {
        guard meetingDetectedObserverToken == nil else { return }
        let token = NotificationCenter.default.addObserver(
            forName: AppDelegate.meetingDetectedWSEventName,
            object: nil,
            queue: .main
        ) { note in
            guard let json = note.userInfo as? [String: Any] else { return }
            guard let eventType = json["event_type"] as? String else { return }
            Task { @MainActor in
                guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
                appDelegate.handleMeetingDetectedWSEvent(eventType: eventType, json: json)
            }
        }
        meetingDetectedObserverToken = token

        #if DEBUG
        DevLogger.shared.info("[MeetingDetectedMiniPanel] AppDelegate observer registered", context: "MeetingDetectedMiniPanel")
        #endif
    }

    @MainActor
    private func handleMeetingDetectedWSEvent(eventType: String, json: [String: Any]) {
        switch eventType {
        case "meeting_detected":
            guard let meeting = DetectedMeetingInfo(json: json) else {
                #if DEBUG
                DevLogger.shared.warning("[MeetingDetectedMiniPanel] meeting_detected payload could not be decoded", context: "MeetingDetectedMiniPanel")
                #endif
                return
            }
            if statusBarManager?.windowCoordinator.meetingSessionCoordinator.shouldSuppressDetectedMeetingPrompt == true {
                #if DEBUG
                DevLogger.shared.info(
                    "[MeetingDetectedMiniPanel] Suppressed detected meeting while another detected meeting is launching or recording",
                    context: "MeetingDetectedMiniPanel"
                )
                #endif
                return
            }
            if meeting.mode == "auto_start" {
                // Skip the prompt entirely and arm transcription immediately.
                launchDetectedMeeting(meeting)
            } else {
                let controller = ensureMeetingDetectedMiniPanelController()
                controller.present(meeting: meeting)
            }

        case "meeting_ended":
            // Backend only emits this when auto_end is enabled. If we
            // auto-started a recording for this app, finalize it via the normal
            // end-meeting path; otherwise leave any manual recording alone.
            let bundleID = json["bundle_id"] as? String ?? ""
            guard !bundleID.isEmpty else { return }
            statusBarManager?.windowCoordinator.finalizeLiveTranscription(forEndedBundleID: bundleID)

        case "meeting_prompt_expired":
            // Backend determined the calendar event backing an open join prompt
            // has ended with no user action; it has already suppressed the
            // event server-side. Just hide the panel if it's currently showing
            // this event.
            guard let eventID = json["calendar_event_id"] as? String, !eventID.isEmpty else { return }
            meetingDetectedMiniPanelController?.hideForExpiredCalendarEvent(eventID: eventID)

        default:
            break
        }
    }

    /// Open the live-transcription window and start recording the detected
    /// meeting's audio source. The armed-start implementation lives on the
    /// window coordinator/controller; this is the AppDelegate entry point the
    /// panel and auto_start mode both funnel through.
    @MainActor
    func launchDetectedMeeting(_ meeting: DetectedMeetingInfo) {
        guard let coordinator = statusBarManager?.windowCoordinator else {
            #if DEBUG
            DevLogger.shared.error("[MeetingDetectedMiniPanel] No window coordinator to launch detected meeting", context: "MeetingDetectedMiniPanel")
            #endif
            return
        }
        guard coordinator.meetingSessionCoordinator.reserveDetectedMeetingLaunch() else {
            #if DEBUG
            DevLogger.shared.info(
                "[MeetingDetectedMiniPanel] Ignored duplicate detected-meeting launch while another launch or recording is active",
                context: "MeetingDetectedMiniPanel"
            )
            #endif
            return
        }
        Task {
            await suppressDetectedCalendarMeeting(meeting)
        }
        if let joinURL = meeting.calendarJoinURL {
            NSWorkspace.shared.open(joinURL)
        }
        coordinator.showLiveTranscriptionWindow(armWith: meeting)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Subscribe to the "a recording actively started" signal so an open
    /// meeting-detected join prompt is dismissed once a call is already being
    /// recorded elsewhere (any meeting, not just the one being prompted about --
    /// see `MeetingDetectedMiniPanelWindowController.hideForActiveRecording()`).
    /// Idempotent, mirroring `registerMeetingDetectedMiniPanelObserver()`.
    @MainActor
    func registerRecordingDidStartObserver() {
        guard recordingDidStartObserverToken == nil else { return }
        let token = NotificationCenter.default.addObserver(
            forName: .liveTranscriptionRecordingDidStart,
            object: nil,
            queue: .main
        ) { _ in
            Task { @MainActor in
                guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
                appDelegate.meetingDetectedMiniPanelController?.hideForActiveRecording()
            }
        }
        recordingDidStartObserverToken = token
    }

    @MainActor
    func suppressDetectedCalendarMeeting(_ meeting: DetectedMeetingInfo) async {
        guard let eventID = meeting.calendarEventID else { return }
        do {
            _ = try await APIClient.shared.ignoreMeetingDetectionCalendarEvent(eventID: eventID)
        } catch {
            #if DEBUG
            DevLogger.shared.error("[MeetingDetectedMiniPanel] Failed to suppress calendar event \(eventID): \(error.localizedDescription)", context: "MeetingDetectedMiniPanel")
            #endif
        }
    }
}
