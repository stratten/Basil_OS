import AppKit
import SwiftUI

final class StatusBarWindowCoordinator {
    // MARK: - AgentTask Capture Window
    var agentTaskCaptureController: AgentTaskCaptureInputWindowController?
    
    /// Spawns (or no-ops on) the ephemeral capture panel used to take a
    /// brand-new AgentTask from the user.
    ///
    /// IMPORTANT — call sites are intentionally restricted. This must
    /// only be invoked from explicit, user-initiated entry points:
    ///
    ///   • the agentTask hotkey (`HotkeyService.handleAgentTaskHotkey`)
    ///   • the wake-word path (`WebSocketService_AgentTask.handleAgentTaskStarted`,
    ///     GATE 4 — the "no result widget / no follow-up eligible" branch)
    ///   • the "+ new AgentTask" affordance inside the result widget
    ///   • the status-bar menu item
    ///
    /// Do NOT call this from a progress/state event handler (e.g.
    /// `dynamic_step_added`, `dynamic_step_updated`, `agent_progress_update`,
    /// `agentTask_progress`). The capture controller's contract is to take
    /// *new* user input; progress display for an already-running agent
    /// is owned by `AgentTaskResultWidgetController.shared`. Re-entering
    /// this function from a progress event spawns spurious capture
    /// panels whenever the original capture has already closed (which
    /// is the normal lifecycle — it hands off to the result widget
    /// ~0.1s after submit), because the `isVisible` guard below only
    /// dedupes against a *currently-visible* panel, not against an
    /// in-flight agent run.
    @MainActor
    func showAgentTaskCaptureWidget(preGeneratedAgentTaskId: String? = nil) {
        // Only show if not already visible
        guard agentTaskCaptureController?.isVisible != true else { return }
        
        #if DEBUG
        DevLogger.shared.info("Showing agentTask capture widget", context: "StatusBarWindowCoordinator")
        #endif
        
        agentTaskCaptureController = AgentTaskCaptureInputWindowController()
        agentTaskCaptureController?.show(preGeneratedAgentTaskId: preGeneratedAgentTaskId)
    }
    
    @MainActor
    func hideAgentTaskCaptureWidget() {
        #if DEBUG
        DevLogger.shared.info("Hiding agentTask capture widget", context: "StatusBarWindowCoordinator")
        #endif
        
        agentTaskCaptureController?.hide()
        agentTaskCaptureController = nil
    }

    // MARK: - Transcription Window
    @MainActor
    func showTranscriptionWindow(controller: TranscriptionWindowController) {
        controller.show()
    }
    @MainActor
    func hideTranscriptionWindow(controller: TranscriptionWindowController) {
        controller.hide()
    }

    // The Enhanced Suggestion window helpers
    // (`showEnhancedSuggestionWindow` / `showSimpleEnhancedSuggestionWindow`)
    // were removed during the AssistantSession unification along with the
    // backing `EnhancedSuggestionWindowController` type.

    // MARK: - AssistantSession Window
    @MainActor
    func showAssistantSessionWindow() {
        AssistantSessionWindowController.show()
    }

    // MARK: - BasilBoard
    var basilBoardWindowController: BasilBoardWindowController?
    var detachedBasilBoardTabWindowManager: DetachedBasilBoardTabWindowManager?

    @MainActor
    func openBasilBoard() {
        DevLogger.shared.info("Coordinator received BasilBoard show request", context: "BasilBoard")
        if detachedBasilBoardTabWindowManager == nil {
            detachedBasilBoardTabWindowManager = DetachedBasilBoardTabWindowManager()
        }
        let detachedManager = detachedBasilBoardTabWindowManager!
        detachedManager.onOpenMeetingWorkspaceRequested = { [weak self] meetingId in
            self?.openMeetingWorkspace(meetingId: meetingId)
        }
        if basilBoardWindowController == nil {
            let controller = BasilBoardWindowController()
            controller.onDetachTabRequested = { [weak self] tabId in
                self?.detachedBasilBoardTabWindowManager?.openOrFocus(tabId: tabId)
            }
            controller.onBringTabToFrontRequested = { [weak self] tabId in
                self?.detachedBasilBoardTabWindowManager?.openOrFocus(tabId: tabId)
            }
            controller.onOpenMeetingWorkspaceRequested = { [weak self] meetingId in
                self?.openMeetingWorkspace(meetingId: meetingId)
            }
            basilBoardWindowController = controller
            detachedManager.onDetachedTabsChanged = { [weak self] tabIds in
                self?.basilBoardWindowController?.setDetachedTabIds(tabIds)
            }
        }
        basilBoardWindowController?.show()
        basilBoardWindowController?.setDetachedTabIds(detachedManager.detachedTabIds)
    }

    @MainActor
    func toggleBasilBoard() {
        if basilBoardWindowController?.isFrontmost == true {
            basilBoardWindowController?.hide()
            return
        }
        openBasilBoard()
    }

    /// Brings the main BasilBoard window forward and selects a specific
    /// conversation on its Chats tab. Unlike `openBasilBoardAgentTaskOriginTab`,
    /// this always targets the main (non-detached) Board window, since Chats
    /// has no `DetachedBasilBoardTabWindowManager`-managed detached tab window.
    @MainActor
    func openBasilBoardConversationOrigin(originId: String) {
        openBasilBoard()
        basilBoardWindowController?.navigateToAgentTaskOrigin(originType: "conversation", originId: originId)
    }

    @MainActor
    func openBasilBoardAgentTaskOriginTab(tabId: String, originType: String, originId: String) {
        if detachedBasilBoardTabWindowManager == nil {
            detachedBasilBoardTabWindowManager = DetachedBasilBoardTabWindowManager()
        }
        let detachedManager = detachedBasilBoardTabWindowManager!
        detachedManager.onOpenMeetingWorkspaceRequested = { [weak self] meetingId in
            self?.openMeetingWorkspace(meetingId: meetingId)
        }
        detachedManager.openOrFocus(
            tabId: tabId,
            originType: originType,
            originId: originId
        )
    }

    // MARK: - Audio File Uploader
    @MainActor
    func showAudioFileUploader() {
        if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
            appDelegate.showAudioFileUploader()
        } else {
            print("Error: Could not access AppDelegate to show audio file uploader")
        }
    }

    // MARK: - Meeting Session
    private var meetingSessionCoordinatorStorage: MeetingSessionCoordinator?

    @MainActor
    var meetingSessionCoordinator: MeetingSessionCoordinator {
        if let meetingSessionCoordinatorStorage {
            return meetingSessionCoordinatorStorage
        }
        let coordinator = MeetingSessionCoordinator()
        meetingSessionCoordinatorStorage = coordinator
        return coordinator
    }

    /// Default entry point. Opens (or focuses) the WebKit Meeting Assistant
    /// window.
    @MainActor
    func showLiveTranscriptionWindow() {
        meetingSessionCoordinator.showWebMeeting()
    }

    /// Open the WebKit Meeting Assistant window and arm it to auto-start
    /// recording the detected meeting's audio source.
    @MainActor
    func showLiveTranscriptionWindow(armWith meeting: DetectedMeetingInfo) {
        if meeting.bundleID.isEmpty && meeting.canJoinMeeting {
            meetingSessionCoordinator.showWithCalendarContext(meeting)
            return
        }
        meetingSessionCoordinator.showAndStart(arming: meeting)
    }

    /// Finalize an auto-started recording when the backend reports its
    /// meeting ended. No-op unless an auto-started recording matches the
    /// bundle ID.
    @MainActor
    @discardableResult
    func finalizeLiveTranscription(forEndedBundleID bundleID: String) -> Bool {
        meetingSessionCoordinator.finalizeForEndedMeeting(bundleID: bundleID)
    }

    /// Native handoff for BasilBoard's Meetings capability tab: open the
    /// default WebKit window (creating/reusing the session as needed) and
    /// select the given meeting.
    @MainActor
    func openMeetingWorkspace(meetingId: String) {
        Task { [weak self] in
            await self?.meetingSessionCoordinator.selectMeeting(meetingId)
        }
    }

    // MARK: - Microphone Audio Capture Window
    @MainActor
    func testKeyMonitoringAction() {
        let testMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            print("🧪 TEST MONITOR DETECTED KEY: '\(event.charactersIgnoringModifiers ?? "Unknown")' (code: \(event.keyCode))")
            if event.keyCode == 53 {
                print("🧪 TEST MONITOR DETECTED ESCAPE KEY!")
            }
            return event
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) {
            print("🧪 Removing test monitor after 15 seconds")
            NSEvent.removeMonitor(testMonitor!)
        }
        print("🧪 Test key monitor started - press keys for 15 seconds to test!")
        let alert = NSAlert()
        alert.messageText = "Key Monitoring Test Started"
        alert.informativeText = "A temporary key monitor has been started. Press keys (including Escape) for the next 15 seconds to test monitoring."
        alert.alertStyle = .informational
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    // MARK: - Transcription Widget Toggle
    @MainActor
    func toggleTranscriptionWidget(controller: TranscriptionWindowController) {
        if controller.isVisible {
            controller.hide()
        } else {
            controller.show()
        }
    }
} 