import Foundation
import Combine

// MARK: - Timer Management
extension LiveTranscriptionViewModel {
    
    /// Starts the recording time display timer
    func startTimer() {
        timerCancellable = Timer.publish(every: 1, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                self?.updateRecordingTime()
            }
    }
    
    /// Updates the recording time string display
    func updateRecordingTime() {
        guard let startTime = recordingStartTime else { return }
        
        let elapsed = Int(-startTime.timeIntervalSinceNow)
        let minutes = elapsed / 60
        let seconds = elapsed % 60
        recordingTimeString = String(format: "%02d:%02d", minutes, seconds)
    }
    
}

