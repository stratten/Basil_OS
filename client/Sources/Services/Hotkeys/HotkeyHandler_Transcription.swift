import Foundation
import AppKit

@MainActor
protocol TranscriptionHotkeyControlling: AnyObject {
    var isVisible: Bool { get }
    var isStartingRecording: Bool { get }
    var isRecording: Bool { get }
    var hotkeyRecordingState: TranscriptionHotkeyGestureState.ControllerState { get }
    func startRecording() async
    func stopRecording()
    func cancelRecording() async
}

extension TranscriptionWindowController: TranscriptionHotkeyControlling {}

extension HotkeyService {
    @MainActor
    private func transcriptionHotkeyController() -> (any TranscriptionHotkeyControlling)? {
        if let transcriptionControllerOverride {
            return transcriptionControllerOverride
        }
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate,
              let statusBarManager = appDelegate.statusBarManager else {
            return nil
        }
        return statusBarManager.transcriptionController
    }

    @MainActor
    func handleAcceptedTranscriptionDoublePress() {
        guard let controller = transcriptionHotkeyController() else {
            debugPrint("❌ Failed to get AppDelegate or StatusBarManager")
            transcriptionHotkeyGestureState.reset()
            return
        }

        switch transcriptionHotkeyGestureState.acceptPress(
            controllerState: controller.hotkeyRecordingState
        ) {
        case .start(let gestureID):
            Task { @MainActor [weak self, weak controller] in
                guard let self, let controller else { return }
                await controller.startRecording()
                if controller.isRecording,
                   self.transcriptionHotkeyGestureState.consumeDeferredStop(for: gestureID) {
                    controller.stopRecording()
                }
            }
        case .cancelStartup:
            Task { @MainActor [weak controller] in
                await controller?.cancelRecording()
            }
        case .stopRecording:
            controller.stopRecording()
        case .none:
            break
        }
    }

    @MainActor
    func handleTranscriptionDoublePressRelease(pressDuration: TimeInterval) {
        let settings = apiClient.getCachedTranscriptionSettings()
        let thresholdSeconds = Double(settings.pushToTalkThresholdMs) / 1000.0

        guard let controller = transcriptionHotkeyController() else {
            transcriptionHotkeyGestureState.reset()
            return
        }

        let action = transcriptionHotkeyGestureState.release(
            holdDuration: pressDuration,
            threshold: thresholdSeconds,
            pushToTalkEnabled: settings.enablePushToTalk,
            controllerState: controller.hotkeyRecordingState
        )

        if action == .stopRecording {
            controller.stopRecording()
        }
    }

    @MainActor
    func handleTranscriptionHotkey() async {
        // Record press time for push-to-talk
        recordHotkeyPress(hotkeyId: "transcribe_audio")
        
        guard let controller = transcriptionHotkeyController() else {
            debugPrint("❌ Failed to get AppDelegate or StatusBarManager")
            return
        }
        
        debugPrint("\n=== Handling Transcription Hotkey ===")
        
        // Case 1: Widget not initialized - bring it up and start recording
        if !controller.isVisible {
            debugPrint("📝 No widget found, creating new one and starting recording")
            // Instead of just toggling, we'll show and wait for initialization
            await controller.startRecording()
            return
        }
        
        debugPrint("🎯 Widget exists, checking recording state")
        
        if controller.isStartingRecording {
            debugPrint("⏹️ Recording startup in progress, canceling startup")
            await controller.cancelRecording()
            return
        }

        // Case 2: Widget exists but not recording - start recording
        if !controller.isRecording {
            debugPrint("▶️ Widget inactive, starting recording")
            await controller.startRecording()
        }
        // Case 3: Recording in progress - stop recording and begin transcription
        else {
            debugPrint("⏹️ Recording in progress, stopping and beginning transcription")
            controller.stopRecording()
        }
    }
    
    @MainActor
    func handleTranscriptionKeyRelease(pressDuration: TimeInterval) async {
        debugPrint("🔧 ENTERED handleTranscriptionKeyRelease with duration: \(String(format: "%.3f", pressDuration))s")
        
        // Fetch transcription settings to check if push-to-talk is enabled
        let settings = apiClient.getCachedTranscriptionSettings()
        debugPrint("🔧 Fetched settings: enablePushToTalk=\(settings.enablePushToTalk), threshold=\(settings.pushToTalkThresholdMs)ms")
        
        guard settings.enablePushToTalk else {
            // Push-to-talk disabled, use normal behavior (wait for second press)
            #if DEBUG
            DevLogger.shared.info("Push-to-talk disabled for transcription, ignoring key release", context: "HotkeyService")
            #endif
            return
        }
        
        let thresholdSeconds = Double(settings.pushToTalkThresholdMs) / 1000.0
        
        #if DEBUG
        DevLogger.shared.info("Push-to-talk enabled: duration=\(String(format: "%.3f", pressDuration))s, threshold=\(String(format: "%.3f", thresholdSeconds))s", context: "HotkeyService")
        #endif
        
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate,
              let statusBarManager = appDelegate.statusBarManager else {
            #if DEBUG
            DevLogger.shared.error("Could not access AppDelegate or StatusBarManager", context: "HotkeyService")
            #endif
            return
        }
        
        if pressDuration >= thresholdSeconds {
            // Auto-process: threshold exceeded, stop recording
            #if DEBUG
            DevLogger.shared.info("Threshold exceeded (\(String(format: "%.3f", pressDuration))s >= \(String(format: "%.3f", thresholdSeconds))s), auto-stopping transcription", context: "HotkeyService")
            DevLogger.shared.info("Widget state - isVisible: \(statusBarManager.transcriptionController.isVisible), isRecording: \(statusBarManager.transcriptionController.isRecording)", context: "HotkeyService")
            #endif
            
            if statusBarManager.transcriptionController.isStartingRecording {
                await statusBarManager.transcriptionController.cancelRecording()
            } else if statusBarManager.transcriptionController.isRecording {
                #if DEBUG
                DevLogger.shared.info("Calling stopRecording() to complete transcription", context: "HotkeyService")
                #endif
                statusBarManager.transcriptionController.stopRecording()
            }
        } else {
            #if DEBUG
            DevLogger.shared.info("Below threshold (\(String(format: "%.3f", pressDuration))s < \(String(format: "%.3f", thresholdSeconds))s), waiting for second press", context: "HotkeyService")
            #endif
        }
    }

    @MainActor
    func handleCancelRecordingHotkey() async {
        #if DEBUG
        DevLogger.shared.info("Direct call to handleCancelRecordingHotkey", context: "HotkeyService")
        #endif
        
        // Check if transcription is active via AppDelegate and StatusBarManager
        if let appDelegate = NSApplication.shared.delegate as? AppDelegate,
           let statusBarManager = appDelegate.statusBarManager {
            
            // Get the transcription controller
            let transcriptionController = statusBarManager.transcriptionController
            
            // Check if transcription is active and recording
            let isVisible = transcriptionController.isVisible
            let isRecording = transcriptionController.isRecording
            
            #if DEBUG
            DevLogger.shared.info("Cancel recording hotkey handler called - Widget visible: \(isVisible), Recording active: \(isRecording)", context: "HotkeyService")
            #endif
            
            // Only handle Escape key if recording is active
            if isVisible && isRecording {
                #if DEBUG
                DevLogger.shared.info("Recording is active, canceling transcription via direct hotkey handler", context: "HotkeyService")
                #endif
                
                // Call the cancelRecording method
                await transcriptionController.cancelRecording()
                
                #if DEBUG
                DevLogger.shared.info("Recording successfully canceled via direct hotkey handler", context: "HotkeyService")
                #endif
            } else {
                #if DEBUG
                DevLogger.shared.info("Cancel recording hotkey handler called but no active recording to cancel", context: "HotkeyService")
                #endif
            }
        } else {
            #if DEBUG
            DevLogger.shared.error("Could not access AppDelegate or StatusBarManager in cancel recording hotkey handler", context: "HotkeyService")
            #endif
        }
    }
} 