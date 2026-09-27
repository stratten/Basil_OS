import AppKit

final class StatusBarMenuUpdater {
    @MainActor
    static func updateMenuItems(menu: NSMenu, hotkeyService: HotkeyService, statusBarManager: StatusBarManager? = nil) {
        // Update hotkeys toggle state
        if let item = menu.item(withTag: MenuItemTag.hotkeyToggle.rawValue) {
            item.state = hotkeyService.isEnabled ? .on : .off
            item.title = "Hotkeys"
        }

        // Update voice activation toggle state
        if let item = menu.item(withTag: MenuItemTag.voiceListenerToggle.rawValue),
           let manager = statusBarManager {
            item.state = manager.isVoiceListenerEnabled ? .on : .off
            item.title = "Voice Activation (\"Hey Basil\")"
        }

        // Update activity capture toggle state
        if let item = menu.item(withTag: MenuItemTag.activityCaptureToggle.rawValue),
           let manager = statusBarManager {
            // Show/hide based on enabled state in settings
            item.isHidden = !manager.isActivityCaptureEnabled
            
            if !item.isHidden {
                item.state = manager.isActivityCaptureActive ? .on : .off
                item.title = "Activity Capture"
            }
        }

        // Legacy hotkey - commented out (holdover from initial builds)
        // Update capture item with current hotkey and key equivalent
        // if let captureItem = menu.item(withTag: MenuItemTag.capture.rawValue),
        //    let captureBinding = hotkeyService.hotkeyBindings["capture_screen"] {
        //     captureItem.title = "Capture Screen"
        //     updateMenuItemWithHotkeyBinding(item: captureItem, binding: captureBinding)
        // }

        // Update transcription item with current hotkey and key equivalent
        if let transcriptionItem = menu.item(withTag: MenuItemTag.transcription.rawValue),
           let transcriptionBinding = hotkeyService.hotkeyBindings["transcribe_audio"] {
            transcriptionItem.title = "Transcription"
            updateMenuItemWithHotkeyBinding(item: transcriptionItem, binding: transcriptionBinding)
        }

        if let ambientItem = menu.item(withTag: MenuItemTag.ambientSuggestions.rawValue),
           let manager = statusBarManager {
            ambientItem.isHidden = !manager.isAmbientSuggestionsEnabled
            if !ambientItem.isHidden {
                ambientItem.state = manager.isAmbientSuggestionsRunning ? .on : .off
                ambientItem.title = "Proactive Suggestions"
            }
        }

        if let meetingDetectionItem = menu.item(withTag: MenuItemTag.meetingDetection.rawValue),
           let manager = statusBarManager {
            meetingDetectionItem.isHidden = !manager.isMeetingDetectionEnabled
            if !meetingDetectionItem.isHidden {
                meetingDetectionItem.state = manager.isMeetingDetectionRunning ? .on : .off
                meetingDetectionItem.title = "Meeting Detection"
            }
        }
        
        // The legacy `get_suggestions` and `enhanced_suggestions` menu
        // items were removed during the AssistantSession unification.

        // Update conversation item with current hotkey and key equivalent
        if let conversationItem = menu.item(withTag: MenuItemTag.conversation.rawValue),
           let conversationBinding = hotkeyService.hotkeyBindings["conversation_toggle"] {
            conversationItem.title = "Conversation"
            updateMenuItemWithHotkeyBinding(item: conversationItem, binding: conversationBinding)
        }

        // Update Open AssistantSession item with current hotkey and key equivalent
        // Note: This uses title matching since there's no tag, so we need to match base title or with suffix
        if let assistantSessionItem = menu.items.first(where: { $0.title.hasPrefix("Open \(BasilTeamIdentity.assistantSession.displayName)") }),
           let assistantSessionBinding = hotkeyService.hotkeyBindings["assistantSession"] {
            assistantSessionItem.title = "Open \(BasilTeamIdentity.assistantSession.displayName)"
            updateMenuItemWithHotkeyBinding(item: assistantSessionItem, binding: assistantSessionBinding)
        }
        
        // Update Open AgentTask item with current hotkey and key equivalent
        if let agentTaskItem = menu.item(withTag: MenuItemTag.agentTask.rawValue),
           let agentTaskBinding = hotkeyService.hotkeyBindings["agentTask"] {
            agentTaskItem.title = "Open \(BasilTeamIdentity.agentTask.displayName)"
            updateMenuItemWithHotkeyBinding(item: agentTaskItem, binding: agentTaskBinding)
        }
    }

    // Legacy hotkey - commented out (holdover from initial builds)
    // Helper method to get the capture menu title with hotkey
    /*
    @MainActor
    static func getCaptureMenuTitle(hotkeyService: HotkeyService, modifierSymbols: [String: String]) -> String {
        guard let binding = hotkeyService.hotkeyBindings["capture_screen"] else {
            return "Capture Screen"
        }
        let modString = binding.modifiers.map { mod -> String in
            return modifierSymbols[mod.lowercased()] ?? mod
        }.joined(separator: "")
        let keyString = binding.key
        let hotkeyText = modString.isEmpty ? keyString : "\(modString)+\(keyString)"
        return "Capture Screen (\(hotkeyText))"
    }
    */

    // Helper method to get the transcription menu title with hotkey
    @MainActor
    static func getTranscriptionMenuTitle(hotkeyService: HotkeyService, modifierSymbols: [String: String]) -> String {
        guard let binding = hotkeyService.hotkeyBindings["transcribe_audio"] else {
            return "Transcription"
        }
        let modString = binding.modifiers.map { mod -> String in
            return modifierSymbols[mod.lowercased()] ?? mod
        }.joined(separator: "")
        let keyString = binding.key
        let hotkeyText = modString.isEmpty ? keyString : "\(modString)+\(keyString)"
        return "Transcription (\(hotkeyText))"
    }

    // The legacy `getSuggestionsMenuTitle` and
    // `getEnhancedSuggestionsMenuTitle` helpers were removed during the
    // AssistantSession unification.

    // Helper method to get the conversation menu title with hotkey
    @MainActor
    static func getConversationMenuTitle(hotkeyService: HotkeyService, modifierSymbols: [String: String]) -> String {
        guard let binding = hotkeyService.hotkeyBindings["conversation_toggle"] else {
            return "Conversation"
        }
        let modString = binding.modifiers.map { mod -> String in
            return modifierSymbols[mod.lowercased()] ?? mod
        }.joined(separator: "")
        let keyString = binding.key
        let hotkeyText = modString.isEmpty ? keyString : "\(modString)+\(keyString)"
        return "Conversation (\(hotkeyText))"
    }

    // Helper method to get the AssistantSession menu title with hotkey
    @MainActor
    static func getAssistantSessionMenuTitle(hotkeyService: HotkeyService, modifierSymbols: [String: String]) -> String {
        guard let binding = hotkeyService.hotkeyBindings["assistantSession"] else {
            return "Open \(BasilTeamIdentity.assistantSession.displayName)"
        }
        let modString = binding.modifiers.map { modifierSymbols[$0.lowercased()] ?? $0 }.joined(separator: "")
        let keyString = binding.key
        let hotkeyText = modString.isEmpty ? keyString : "\(modString)+\(keyString)"
        return "Open AssistantSession (\(hotkeyText))"
    }
} 