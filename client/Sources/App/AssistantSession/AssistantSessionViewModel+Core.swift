import SwiftUI
import Combine
import Foundation

// MARK: - Core: Initialization and Lifecycle
extension AssistantSessionViewModel {
    
    // MARK: - Async Initialization
    
    func initialize() async {
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] AssistantSessionViewModel initializing...", context: "AssistantSessionViewModel")
        #endif
        
        // Set up audio level monitoring
        audioCaptureService.$audioLevel
            .sink { [weak self] level in
                Task { @MainActor in
                    self?.audioLevel = level
                }
            }
            .store(in: &cancellables)
        
        // Monitor recording state changes and post notifications for escape key handling
        audioCaptureService.$isRecording
            .receive(on: DispatchQueue.main)
            .sink { [weak self] recording in
                guard let self = self else { return }
                let oldState = self.isRecording
                self.isRecording = recording
                
                // Handle timer logic for recording duration
                if recording {
                    self.recordingStartDate = Date()
                    self.elapsedSeconds = 0
                    self.timerCancellable = Timer.publish(every: 1, on: .main, in: .common)
                        .autoconnect()
                        .sink { _ in
                            guard let start = self.recordingStartDate else { return }
                            self.elapsedSeconds = Int(Date().timeIntervalSince(start))
                        }
                } else {
                    self.timerCancellable?.cancel()
                    self.timerCancellable = nil
                }
                
                // Post notification for HotkeyService to manage escape key handling
                NotificationCenter.default.post(
                    name: NSNotification.Name("RecordingStateChanged"),
                    object: nil,
                    userInfo: [
                        "isRecording": recording,
                        "previousState": oldState,
                        "source": "assistantSession"  // Distinguish from transcription
                    ]
                )
                
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Posted RecordingStateChanged notification: \(oldState) -> \(recording)", context: "AssistantSessionViewModel")
                #endif
            }
            .store(in: &cancellables)
        
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] AssistantSessionViewModel initialized successfully", context: "AssistantSessionViewModel")
        #endif
    }
}

