import Foundation
import AppKit
import HotKey

extension HotkeyService {
    // MARK: - Recording State Management
    
    @objc func handleRecordingStateChange(_ notification: Notification) {
        guard let isRecording = notification.userInfo?["isRecording"] as? Bool,
              let source = notification.userInfo?["source"] as? String else { return }
        
        #if DEBUG
        DevLogger.shared.info("HotkeyService received RecordingStateChanged notification - isRecording: \(isRecording), source: \(source)", context: "HotkeyService")
        #endif
        
        if !isEnabled {
            #if DEBUG
            DevLogger.shared.warning("HotkeyService disabled - not setting up Escape key handling", context: "HotkeyService")
            #endif
            return
        }
        
        // Check if ANY recording service is active (transcription OR AssistantSession)
        let isAnyRecordingActive = checkForActiveRecording()
        
        #if DEBUG
        DevLogger.shared.info("Recording state check - isRecording: \(isRecording), source: \(source), anyActive: \(isAnyRecordingActive)", context: "HotkeyService")
        #endif
        
        // Set up escape key handling if any recording is active, remove if none are active
        if isAnyRecordingActive {
            // Only set up if not already set up
            if escapeHotKey == nil {
                setupEscapeKeyHandling()
            }
        } else {
            // Clean up when no recording is active
            cleanupEscapeKeyHandlers()
        }
    }
    
    // Check if any recording service (transcription, AssistantSession, or agentTask) is currently active
    private func checkForActiveRecording() -> Bool {
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate,
              let statusBarManager = appDelegate.statusBarManager else {
            return false
        }
        
        let transcriptionRecording = statusBarManager.transcriptionController.isRecording
        let assistantSessionRecording = AssistantSessionWindowController.sharedController?.viewModel.isRecording ?? false
        // `activeCaptureViewModel()` only sees the dedicated capture
        // window (initial new-agent-task captures). Inline follow-up
        // captures live on the result-widget singleton's
        // `followUpCaptureVM` and are invisible to that helper, so we
        // OR-in the singleton's own `isFollowUpCapturing` flag.
        // Without this, pressing Escape during a follow-up did
        // nothing: this method returned false, so
        // `setupEscapeKeyHandling()` was never called and the global
        // Escape hotkey wasn't even registered.
        let agentTaskCapturing = (activeCaptureViewModel()?.isCapturing ?? false)
            || AgentTaskFollowUpCaptureLease.shared.ownerID != nil
        
        #if DEBUG
        DevLogger.shared.info("Recording state check - Transcription: \(transcriptionRecording), AssistantSession: \(assistantSessionRecording), AgentTask: \(agentTaskCapturing)", context: "HotkeyService")
        #endif
        
        return transcriptionRecording || assistantSessionRecording || agentTaskCapturing
    }
    
    // Set up escape key handling for any active recording
    private func setupEscapeKeyHandling() {
        // Clean up any existing handlers first
        cleanupEscapeKeyHandlers()
        
        #if DEBUG
        DevLogger.shared.info("Setting up Escape key handling for active recording using HotKey library", context: "HotkeyService")
        #endif
        
        // Create a direct hotkey using the HotKey library
        escapeHotKey = HotKey(key: .escape, modifiers: [])
        
        // Set up the key handler
        escapeHotKey?.keyDownHandler = { [weak self] in
            #if DEBUG
            DevLogger.shared.info("ESCAPE KEY PRESSED via HotKey library during recording", context: "HotkeyService")
            #endif
            
            guard let self = self else { return }
            self.handleEscapeKeyPress()
        }
        
        #if DEBUG
        DevLogger.shared.info("Escape hotkey successfully registered with HotKey library", context: "HotkeyService")
        #endif
    }
    
    // Handle escape key press by determining which service is recording and calling appropriate cancellation
    private func handleEscapeKeyPress() {
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate,
              let statusBarManager = appDelegate.statusBarManager else {
            #if DEBUG
            DevLogger.shared.warning("Cannot access StatusBarManager for escape key handling", context: "HotkeyService")
            #endif
            return
        }
        
        let transcriptionRecording = statusBarManager.transcriptionController.isRecording
        let assistantSessionRecording = AssistantSessionWindowController.sharedController?.viewModel.isRecording ?? false
        let captureWidgetCapturing = activeCaptureViewModel()?.isCapturing ?? false
        // Inline follow-up captures live on the result-widget singleton,
        // not on the dedicated capture-window controller, so they need
        // their own probe + cancellation branch — see the matching
        // comment in checkForActiveRecording().
        let resultWidgetFollowUpCapturing = AgentTaskFollowUpCaptureLease.shared.ownerID != nil
        let agentTaskCapturing = captureWidgetCapturing || resultWidgetFollowUpCapturing
        
        #if DEBUG
        DevLogger.shared.info("Escape key handler - Transcription: \(transcriptionRecording), Voice suggestion: \(assistantSessionRecording), AgentTask (capture widget): \(captureWidgetCapturing), AgentTask (result-widget follow-up): \(resultWidgetFollowUpCapturing)", context: "HotkeyService")
        #endif
        
        // Handle transcription cancellation (existing behavior)
        if transcriptionRecording {
            Task { @MainActor in
                #if DEBUG
                DevLogger.shared.info("Calling cancelRecording via HotKey handler for transcription", context: "HotkeyService")
                #endif
                
                await statusBarManager.transcriptionController.cancelRecording()
                
                #if DEBUG
                DevLogger.shared.info("Transcription recording canceled via HotKey handler", context: "HotkeyService")
                #endif
            }
        }
        
        // Handle AssistantSession cancellation
        if assistantSessionRecording {
            Task { @MainActor in
                #if DEBUG
                DevLogger.shared.info("Calling cancelOperation via HotKey handler for AssistantSession", context: "HotkeyService")
                #endif
                
                AssistantSessionWindowController.sharedController?.viewModel.cancelOperation()
                
                #if DEBUG
                DevLogger.shared.info("Voice suggestion recording canceled via HotKey handler", context: "HotkeyService")
                #endif
            }
        }
        
        // Handle agentTask capture-widget cancellation via the controller's
        // cleanup path, which correctly handles initial new-agent-task and
        // overlay captures hosted by the dedicated capture window.
        if captureWidgetCapturing {
            if let appDelegate = NSApplication.shared.delegate as? AppDelegate,
               let coordinator = appDelegate.statusBarManager?.windowCoordinator,
               let controller = coordinator.agentTaskCaptureController {
                Task { @MainActor in
                    #if DEBUG
                    DevLogger.shared.info("Calling cancelActiveCapture via HotKey handler for agentTask capture widget", context: "HotkeyService")
                    #endif
                    
                    controller.cancelActiveCapture()
                    
                    #if DEBUG
                    DevLogger.shared.info("AgentTask capture widget canceled via HotKey handler", context: "HotkeyService")
                    #endif
                }
            }
        }
        
        // Handle inline follow-up cancellation on the result-widget
        // singleton. This is a separate code path from the capture
        // widget above because follow-up captures intentionally never
        // route through AgentTaskCaptureWindowController — they are owned
        // inline by the result widget so the user stays in the same
        // panel (see AgentTaskCaptureWindowController's header doc and
        // AgentTaskResultWidgetController.cancelActiveFollowUpCapture).
        if resultWidgetFollowUpCapturing {
            Task { @MainActor in
                #if DEBUG
                DevLogger.shared.info("Calling cancelActiveFollowUpCapture via HotKey handler for result-widget follow-up", context: "HotkeyService")
                #endif
                
                _ = AgentTaskFollowUpCaptureLease.shared.cancelActiveCapture()
                
                #if DEBUG
                DevLogger.shared.info("Result-widget follow-up capture canceled via HotKey handler", context: "HotkeyService")
                #endif
            }
        }
        
        // If none are recording, log a warning
        if !transcriptionRecording && !assistantSessionRecording && !agentTaskCapturing {
            #if DEBUG
            DevLogger.shared.warning("HotKey handler called but no active recording found", context: "HotkeyService")
            #endif
        }
    }
    
    @MainActor
    func cleanupEscapeKeyHandlers() {
        // Remove HotKey binding if it exists
        if escapeHotKey != nil {
            #if DEBUG
            DevLogger.shared.info("Removing Escape HotKey binding", context: "HotkeyService")
            #endif
            
            escapeHotKey?.keyDownHandler = nil
            escapeHotKey?.keyUpHandler = nil
            escapeHotKey = nil
        }
        
        // Remove local monitor if it exists
        if let monitor = escapeKeyMonitor {
            #if DEBUG
            DevLogger.shared.info("Removing local Escape key monitor", context: "HotkeyService")
            #endif
            
            NSEvent.removeMonitor(monitor)
            escapeKeyMonitor = nil
        }
        
        // Remove backup global monitor if it exists
        if let monitor = backupEscapeKeyMonitor {
            #if DEBUG
            DevLogger.shared.info("Removing backup global Escape key monitor", context: "HotkeyService")
            #endif
            
            NSEvent.removeMonitor(monitor)
            backupEscapeKeyMonitor = nil
        }
        
        #if DEBUG
        DevLogger.shared.info("All Escape key handlers cleaned up", context: "HotkeyService")
        #endif
    }
} 