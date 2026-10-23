import AppKit
import SwiftUI

// MARK: - Window Management
extension AppDelegate {
    @MainActor
    func toggleTranscriptionWidget() {
        statusBarManager.toggleTranscriptionWidget()
    }
    
    // MARK: - Audio File Upload
    @MainActor
    func showAudioFileUploader() {
        AudioFileUploadWindowController.show()
    }
    
    @MainActor
    func hideStartupLoadingWindow() {
        startupLoadingWindow?.hideWindow()
        startupLoadingWindow = nil
        
        #if DEBUG
        print("🏁 Startup loading sequence completed")
        #endif
    }
}