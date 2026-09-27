import AppKit

final class StatusBarMenuBuilder {
    @MainActor
    static func buildMenu(hotkeyService: HotkeyService, target: AnyObject) -> NSMenu {
        let menu = NSMenu()

        // Settings
        let newSettingsItem = NSMenuItem(
            title: "Settings",
            action: #selector(StatusBarManager.openNewSettings),
            keyEquivalent: ""
        )
        newSettingsItem.target = target
        newSettingsItem.tag = MenuItemTag.settings.rawValue
        menu.addItem(newSettingsItem)

        let basilHomeItem = NSMenuItem(title: "Basil Home", action: #selector(StatusBarManager.openBasilBoard), keyEquivalent: "")
        basilHomeItem.target = target
        menu.addItem(basilHomeItem)

        // Separator
        menu.addItem(NSMenuItem.separator())

        // Hotkeys toggle
        let hotkeysItem = NSMenuItem(
            title: "Hotkeys",
            action: #selector(StatusBarManager.toggleHotkeys),
            keyEquivalent: ""
        )
        hotkeysItem.target = target
        hotkeysItem.tag = MenuItemTag.hotkeyToggle.rawValue
        menu.addItem(hotkeysItem)

        // Voice Activation toggle
        let voiceListenerItem = NSMenuItem(
            title: "Voice Activation (\"Hey Basil\")",
            action: #selector(StatusBarManager.toggleVoiceListener),
            keyEquivalent: ""
        )
        voiceListenerItem.target = target
        voiceListenerItem.tag = MenuItemTag.voiceListenerToggle.rawValue
        menu.addItem(voiceListenerItem)

        // Activity Capture toggle (only show if enabled in settings)
        let activityCaptureItem = NSMenuItem(
            title: "Activity Capture",
            action: #selector(StatusBarManager.toggleActivityCapture),
            keyEquivalent: ""
        )
        activityCaptureItem.target = target
        activityCaptureItem.tag = MenuItemTag.activityCaptureToggle.rawValue
        activityCaptureItem.isHidden = true // Hidden by default, shown only if enabled in settings
        menu.addItem(activityCaptureItem)

        // Meeting Detection start/stop. Hidden unless enabled in Settings; the
        // user manually starts/stops the mechanical monitor from here.
        let meetingDetectionItem = NSMenuItem(title: "Meeting Detection", action: #selector(StatusBarManager.toggleMeetingDetection), keyEquivalent: "")
        meetingDetectionItem.target = target
        meetingDetectionItem.tag = MenuItemTag.meetingDetection.rawValue
        meetingDetectionItem.isHidden = true
        menu.addItem(meetingDetectionItem)

        // Separator between monitoring toggle and hotkeys section
        menu.addItem(NSMenuItem.separator())

        /* // Capture Screen (commented out per user request)
        let captureItem = NSMenuItem(title: "Capture Screen", action: #selector(StatusBarManager.handleCaptureAction), keyEquivalent: "")
        captureItem.target = target
        captureItem.tag = MenuItemTag.capture.rawValue
        menu.addItem(captureItem)
        if let captureBinding = hotkeyService.hotkeyBindings["capture_screen"] {
            updateMenuItemWithHotkeyBinding(item: captureItem, binding: captureBinding)
        }
        */

        // Conversation
        let conversationItem = NSMenuItem(title: "Conversation", action: #selector(StatusBarManager.handleConversationAction), keyEquivalent: "")
        conversationItem.target = target
        conversationItem.tag = MenuItemTag.conversation.rawValue
        menu.addItem(conversationItem)
        if let conversationBinding = hotkeyService.hotkeyBindings["conversation_toggle"] {
            updateMenuItemWithHotkeyBinding(item: conversationItem, binding: conversationBinding)
        }

        // Transcription
        let transcriptionItem = NSMenuItem(title: "Transcription", action: #selector(StatusBarManager.toggleTranscriptionWidget), keyEquivalent: "")
        transcriptionItem.target = target
        transcriptionItem.tag = MenuItemTag.transcription.rawValue
        menu.addItem(transcriptionItem)
        if let transcriptionBinding = hotkeyService.hotkeyBindings["transcribe_audio"] {
            updateMenuItemWithHotkeyBinding(item: transcriptionItem, binding: transcriptionBinding)
        }

        // Transcription History (indented under Transcription)
        let transcriptionHistoryItem = NSMenuItem(title: "   Transcription History", action: #selector(StatusBarManager.openTranscriptionHistory), keyEquivalent: "")
        transcriptionHistoryItem.target = target
        transcriptionHistoryItem.tag = MenuItemTag.transcriptionHistory.rawValue
        menu.addItem(transcriptionHistoryItem)

        // Transcribe Audio File (indented under Transcription)
        let audioUploadItem = NSMenuItem(title: "   Transcribe Audio File", action: #selector(StatusBarManager.showAudioFileUploader), keyEquivalent: "")
        audioUploadItem.target = target
        audioUploadItem.tag = MenuItemTag.audioUpload.rawValue
        menu.addItem(audioUploadItem)

        // The legacy "Suggestions" (F9) and "Enhanced Suggestions" (F10)
        // menu items were removed during the AssistantSession unification --
        // both modalities now live behind "Open \(BasilTeamIdentity.assistantSession.displayName)" with
        // an in-widget speak/type toggle.

        // Open AssistantSession
        let assistantSessionItem = NSMenuItem(title: "Open \(BasilTeamIdentity.assistantSession.displayName)", action: #selector(StatusBarManager.openAssistantSession), keyEquivalent: "")
        assistantSessionItem.target = target
        menu.addItem(assistantSessionItem)
        if let assistantSessionBinding = hotkeyService.hotkeyBindings["assistantSession"] {
            updateMenuItemWithHotkeyBinding(item: assistantSessionItem, binding: assistantSessionBinding)
        }

        // Open AgentTask
        let agentTaskItem = NSMenuItem(title: "Open \(BasilTeamIdentity.agentTask.displayName)", action: #selector(StatusBarManager.openAgentTask), keyEquivalent: "")
        agentTaskItem.target = target
        agentTaskItem.tag = MenuItemTag.agentTask.rawValue
        menu.addItem(agentTaskItem)
        if let agentTaskBinding = hotkeyService.hotkeyBindings["agentTask"] {
            updateMenuItemWithHotkeyBinding(item: agentTaskItem, binding: agentTaskBinding)
        }

        // Separator before additional features
        menu.addItem(NSMenuItem.separator())

        let ambientSuggestionsItem = NSMenuItem(title: "Proactive Suggestions", action: #selector(StatusBarManager.openAmbientSuggestions), keyEquivalent: "")
        ambientSuggestionsItem.target = target
        ambientSuggestionsItem.tag = MenuItemTag.ambientSuggestions.rawValue
        ambientSuggestionsItem.isHidden = true
        menu.addItem(ambientSuggestionsItem)

        // Meeting / Call Transcription (formerly "Open Live Transcription").
        let liveTranscriptionItem = NSMenuItem(title: "Meeting / Call Transcription", action: #selector(StatusBarManager.openLiveTranscription), keyEquivalent: "")
        liveTranscriptionItem.target = target
        menu.addItem(liveTranscriptionItem)

        /* --- Beta Features Submenu (commented out until we have more beta features) ---
        // Separator before Beta Features submenu
        menu.addItem(NSMenuItem.separator())

        let betaFeaturesMenu = NSMenu()
        betaFeaturesMenu.title = "Beta Features"

        let keyMonitoringItem = NSMenuItem(title: "Test Key Monitoring", action: #selector(StatusBarManager.testKeyMonitoringAction), keyEquivalent: "")
        keyMonitoringItem.target = target
        betaFeaturesMenu.addItem(keyMonitoringItem)

        let betaFeaturesMenuItem = NSMenuItem(title: "Beta Features", action: nil, keyEquivalent: "")
        betaFeaturesMenuItem.submenu = betaFeaturesMenu
        menu.addItem(betaFeaturesMenuItem)
        // --- End Beta Features Submenu --- */

        #if DEBUG
        // Separator before Developer submenu
        menu.addItem(NSMenuItem.separator())

        let developerMenu = NSMenu()
        developerMenu.title = "Developer"

        let triggerTrialExhaustionItem = NSMenuItem(title: "Trigger Trial Exhaustion Alert", action: #selector(StatusBarManager.triggerTrialExhaustionDebugAction), keyEquivalent: "")
        triggerTrialExhaustionItem.target = target
        developerMenu.addItem(triggerTrialExhaustionItem)

        let resetTrialBalanceItem = NSMenuItem(title: "Reset Trial Balance", action: #selector(StatusBarManager.resetTrialBalanceDebugAction), keyEquivalent: "")
        resetTrialBalanceItem.target = target
        developerMenu.addItem(resetTrialBalanceItem)

        let triggerSetupAssistantResumeToastItem = NSMenuItem(title: "Trigger Setup Assistant Resume Toast", action: #selector(StatusBarManager.triggerSetupAssistantResumeToastDebugAction), keyEquivalent: "")
        triggerSetupAssistantResumeToastItem.target = target
        developerMenu.addItem(triggerSetupAssistantResumeToastItem)

        let developerMenuItem = NSMenuItem(title: "Developer", action: nil, keyEquivalent: "")
        developerMenuItem.submenu = developerMenu
        menu.addItem(developerMenuItem)
        #endif

        // Separator before quit
        menu.addItem(NSMenuItem.separator())

        // Quit
        let quitItem = NSMenuItem(title: "Quit", action: #selector(StatusBarManager.quitApp), keyEquivalent: "")
        quitItem.target = target
        quitItem.tag = MenuItemTag.quit.rawValue
        menu.addItem(quitItem)

        return menu
    }
} 