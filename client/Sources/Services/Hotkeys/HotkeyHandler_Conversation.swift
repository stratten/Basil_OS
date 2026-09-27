import Foundation
import AppKit

extension HotkeyService {
    @MainActor
    func handleConversationHotkey() async {
        do {
            _ = try await apiClient.post("/hotkeys/conversation")
            
            // Ensure the ConversationWidgetManager is initialized and toggle the widget
            let manager = ConversationWidgetManager.shared
            manager.toggle()
            
            #if DEBUG
            DevLogger.shared.info("Toggled conversation widget", context: "HotkeyService")
            #endif
        } catch {
            print("Failed to handle conversation hotkey: \(error)")
            #if DEBUG
            DevLogger.shared.error("Failed to handle conversation hotkey: \(error)", context: "HotkeyService")
            #endif
        }
    }
} 