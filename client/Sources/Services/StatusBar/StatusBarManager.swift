import AppKit
import SwiftUI
import Combine

// Move MenuItemTag to top-level so it is accessible from StatusBarMenuBuilder
internal enum MenuItemTag: Int {
    case settings = 100
    case hotkeyToggle = 101
    case voiceListenerToggle = 102
    case activityCaptureToggle = 103
    case capture = 104
    case transcription = 105
    // 106 (suggestions) and 107 (enhancedSuggestions) were removed during
    // the AssistantSession unification -- their menu items no longer exist.
    case conversation = 108
    case meeting = 109
    case audioUpload = 110
    case quit = 111
    case systemAudioRecording = 1008
    case transcriptionHistory = 112
    case agentTask = 113
    case ambientSuggestions = 114
    case meetingDetection = 115
}

@MainActor
final class StatusBarManager: StatusBarServiceProtocol {
    // MARK: - Properties
    var statusBarItem: StatusBarItem
    var statusBarProvider: StatusBarItemProvider
    var transcriptionController: TranscriptionWindowController
    var hotkeyService = HotkeyService.shared
    var notificationTask: Task<Void, Never>?
    var cancellables = Set<AnyCancellable>()
    var windowCoordinator = StatusBarWindowCoordinator()
    
    // Voice listener state tracking
    @Published var isVoiceListenerEnabled: Bool = false
    
    // Activity capture state tracking
    @Published var isActivityCaptureEnabled: Bool = false
    @Published var isActivityCaptureActive: Bool = false
    @Published var isAmbientSuggestionsEnabled: Bool = false
    @Published var isAmbientSuggestionsRunning: Bool = false

    // Meeting detection state tracking
    @Published var isMeetingDetectionEnabled: Bool = false
    @Published var isMeetingDetectionRunning: Bool = false
    
    var isEnabled: Bool {
        get async {
            await MainActor.run { statusBarItem.statusItem != nil }
        }
    }
    
    // MARK: - Initialization
    init(statusBarProvider: StatusBarItemProvider = NSStatusBar.system) {
        #if DEBUG
        DevLogger.shared.info("Initializing StatusBarManager", context: "StatusBar")
        #endif
        self.statusBarProvider = statusBarProvider
        self.statusBarItem = StatusBarItem(statusBarProvider: statusBarProvider)
        self.transcriptionController = TranscriptionWindowController()
        
        // Set the manager reference after initialization to avoid circular dependency
        self.statusBarItem.statusBarManager = self
        
        // Initial setup - need to use Task since setupStatusBar is now MainActor-isolated
        Task { @MainActor in
        statusBarItem.setupStatusBar()
        setupMenu()
        }
        #if DEBUG
        DevLogger.shared.info("StatusBar setup complete", context: "StatusBar")
        #endif
        // Listen for hotkey service state changes
        notificationTask = Task { @MainActor in
            // Listen for enabled/disabled state changes
            let stateNotificationName = NSNotification.Name("HotkeyStateChanged")
            let stateNotifications = NotificationCenter.default.notifications(named: stateNotificationName)
            
            // Listen for hotkey bindings changes
            let bindingsNotificationName = NSNotification.Name("HotkeyBindingsChanged")
            let bindingsNotifications = NotificationCenter.default.notifications(named: bindingsNotificationName)
            
            // Listen for recording state changes (backup method)
            let recordingStateName = NSNotification.Name("RecordingStateChanged")
            let recordingStateNotifications = NotificationCenter.default.notifications(named: recordingStateName)
            
            // Create a Sendable-compliant wrapper for the notification data
            struct NotificationData: Sendable {
                let name: String
                let isRecording: Bool?
            }
            
            // Convert notification streams to Sendable-compliant data
            let stateStream = stateNotifications.map { notification in
                NotificationData(name: notification.name.rawValue, isRecording: nil)
            }
            
            let bindingsStream = bindingsNotifications.map { notification in
                NotificationData(name: notification.name.rawValue, isRecording: nil)
            }
            
            let recordingStream = recordingStateNotifications.map { notification in
                NotificationData(name: notification.name.rawValue, 
                                isRecording: notification.userInfo?["isRecording"] as? Bool)
            }
            
            // Merge the notification streams
            for await data in merge3(stateStream, bindingsStream, recordingStream) {
                if data.name == "RecordingStateChanged" {
                    if let isRecording = data.isRecording {
                        setRecording(isRecording)
                    }
                } else {
                    setActive(hotkeyService.isEnabled)
                    if let menu = statusBarItem.statusMenu {
                        StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
                    }
                }
            }
        }
        // Listen for recording state changes via publisher
        transcriptionController.recordingStatePublisher
            .sink { [weak self] isRecording in
                Task { @MainActor in
                    guard let self = self else { return }
                    self.setRecording(isRecording)
                }
            }
            .store(in: &cancellables)
        // Force menu update with hotkey data (no delay)
        Task { @MainActor in
            if let menu = statusBarItem.statusMenu {
                StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
            }
        }
        
        // Don't load initial states immediately - wait for backend availability
        Task { @MainActor in
            // Both voice listener and activity capture state loading will be handled
            // by loadStatesWhenBackendReady() to avoid timing issues
        }
    }
    
    /// Waits for backend to become available, then loads voice listener and activity capture states
    @MainActor
    func loadStatesWhenBackendReady() async {
        let maxWaitTime: TimeInterval = 30.0 // 30 second timeout
        let checkInterval: TimeInterval = 0.5 // Check every 500ms
        let startTime = Date()
        
        #if DEBUG
        DevLogger.shared.info("🔄 STARTUP: Waiting for backend availability to load StatusBar states (timeout: \(maxWaitTime)s)...", context: "StatusBarManager")
        #endif
        
        while Date().timeIntervalSince(startTime) < maxWaitTime {
            if APIClient.shared.isBackendAvailable {
                #if DEBUG
                DevLogger.shared.info("✅ STARTUP: Backend is now available. Loading StatusBar states...", context: "StatusBarManager")
                #endif
                
            await loadInitialVoiceListenerState()
            await loadInitialActivityCaptureState()
            await refreshAmbientSuggestionState()
            await refreshMeetingDetectionState()
                return
            }
            
            // Wait before next check
            try? await Task.sleep(nanoseconds: UInt64(checkInterval * 1_000_000_000))
        }
        
        #if DEBUG
        DevLogger.shared.error("⏰ STARTUP: Timeout waiting for backend availability (\(maxWaitTime)s). StatusBar states not loaded.", context: "StatusBarManager")
        #endif
    }
    
    deinit {
        notificationTask?.cancel()
        notificationTask = nil
    }
    
    // MARK: - Menu Setup
    func setupMenu() {
        #if DEBUG
        DevLogger.shared.info("Setting up status menu", context: "StatusBar")
        #endif
        let menu = StatusBarMenuBuilder.buildMenu(hotkeyService: hotkeyService, target: self)
        statusBarItem.statusItem?.menu = menu
        statusBarItem.statusMenu = menu
        if let item = menu.item(withTag: MenuItemTag.hotkeyToggle.rawValue) {
            item.state = hotkeyService.isEnabled ? .on : .off
            item.title = "Hotkeys"
        }
        if let item = menu.item(withTag: MenuItemTag.voiceListenerToggle.rawValue) {
            item.state = isVoiceListenerEnabled ? .on : .off
            item.title = "Voice Activation (\"Hey Basil\")"
        }
    }
    
    @objc func toggleHotkeys() {
        Task { @MainActor in
            hotkeyService.toggleHotkeys()
            if let menu = statusBarItem.statusMenu {
                StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
            }
            
            // Update icon to reflect new hotkey state
            statusBarItem.updateIconForCurrentState()
        }
    }
    
    @objc func toggleVoiceListener() {
        Task { @MainActor in
            #if DEBUG
            DevLogger.shared.info("🔊 StatusBar: Toggle voice listener requested", context: "StatusBarManager")
            #endif
            
            // Calculate the new desired state
            let newState = !isVoiceListenerEnabled
            
            do {
                // Call the backend API to enable/disable voice listener
                let result = try await APIClient.shared.updateVoiceListenerSettings(enabled: newState)
                
                // Update local state based on backend response
                isVoiceListenerEnabled = result.voiceListenerEnabled
                
                #if DEBUG
                DevLogger.shared.info("✅ StatusBar: Voice listener successfully toggled to: \(isVoiceListenerEnabled)", context: "StatusBarManager")
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ StatusBar: Failed to toggle voice listener: \(error.localizedDescription)", context: "StatusBarManager")
                #endif
                // Don't update local state if API call failed
            }
            
            // Update menu items with current state
            if let menu = statusBarItem.statusMenu {
                StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
            }
            
            // Update icon to reflect new voice listener state
            statusBarItem.updateIconForCurrentState()
        }
    }
    
    @objc func toggleActivityCapture() {
        Task { @MainActor in
            #if DEBUG
            DevLogger.shared.info("📸 StatusBar: Toggle activity capture requested", context: "StatusBarManager")
            #endif
            
            // Calculate the new desired state
            let newState = !isActivityCaptureActive
            
            do {
                // Toggle activity capture using the new unified endpoint
                _ = try await APIClient.shared.post("/activity-capture/toggle")
                
                // Update state based on API response (the API tells us the new state)
                isActivityCaptureActive = newState
                
                #if DEBUG
                let action = newState ? "started" : "stopped"
                DevLogger.shared.info("✅ StatusBar: Activity capture successfully \(action)", context: "StatusBarManager")
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ StatusBar: Failed to toggle activity capture: \(error.localizedDescription)", context: "StatusBarManager")
                #endif
                // Don't update local state if API call failed
            }
            
            // Update menu items with current state
            if let menu = statusBarItem.statusMenu {
                StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
            }
            
            // Update icon to reflect new activity capture state
            statusBarItem.updateIconForCurrentState()
        }
    }
    
    @objc func handleCaptureAction() {
        Task { @MainActor in
            do {
                print("Initiating screen capture from menu...")
                _ = try await APIClient.shared.post("/capture")
                print("✅ Screen capture request sent successfully")
            } catch {
                print("❌ Error initiating screen capture: \(error)")
            }
        }
    }
    
    @objc func handleConversationAction() {
        Task { @MainActor in
            print("Toggling conversation from menu...")
            await hotkeyService.handleConversationHotkey()
            print("✅ Conversation toggled successfully")
        }
    }

    @objc func showAudioFileUploader() {
        windowCoordinator.showAudioFileUploader()
    }
    
    // MARK: - StatusBarServiceProtocol
    func enableStatusItem() async {
        statusBarItem.setupStatusBar()
    }
    
    func disableStatusItem() async {
        if let statusItem = statusBarItem.statusItem {
            // Clear menu first to prevent any retain cycles
            statusItem.menu = nil
            statusBarItem.statusMenu = nil
            
            // Remove from status bar directly
            statusBarProvider.removeStatusItem(statusItem)
            statusBarItem.statusItem = nil
        }
    }
    
    @MainActor
    func updateIcon(_ icon: NSImage) {
        statusBarItem.statusItem?.button?.image = icon
    }
    
    @MainActor
    func updateTitle(_ title: String) {
        statusBarItem.statusItem?.button?.title = title
    }
    
    @MainActor
    func setActive(_ active: Bool) {
        statusBarItem.isActiveState = active
        statusBarItem.updateIconForCurrentState()
    }
    
    @MainActor
    func setRecording(_ recording: Bool) {
        statusBarItem.isRecordingState = recording
        statusBarItem.updateIconForCurrentState()
    }
    
    @objc func openNewSettings() {
        SettingsShellWindowController.shared.show()
    }
    
    @objc func quitApp() {
        Task { @MainActor in
            // 1) Close user-visible UI promptly
            transcriptionController.hide()

            // 2) Fire backend shutdown, but don't block quit
            APIClient.isBackendShuttingDown = true
            #if DEBUG
            DevLogger.shared.info("🚩 Setting APIClient.isBackendShuttingDown = true", context: "StatusBarManager")
            #endif

            let shutdownTask = Task.detached(priority: .background) {
                do {
                    _ = try await APIClient.shared.post("/shutdown")
                    #if DEBUG
                    DevLogger.shared.info("🛑 Backend shutdown request sent (detached)", context: "StatusBarManager")
                    #endif
                } catch {
                    #if DEBUG
                    DevLogger.shared.warning("⚠️ Backend shutdown request failed: \(error.localizedDescription)", context: "StatusBarManager")
                    #endif
                }
            }

            // Optional: give the detached task up to 1s, then proceed regardless
            _ = await shutdownTask.result

            // 3) Terminate app regardless of backend response
            NSApplication.shared.terminate(nil)
        }
    }
    
    @objc @MainActor
    func toggleTranscriptionWidget() {
        windowCoordinator.toggleTranscriptionWidget(controller: transcriptionController)
    }
    
    @objc func openAssistantSession() {
        Task { @MainActor in
            await hotkeyService.handleAssistantSessionHotkey()
        }
    }
    
    @objc func openLiveTranscription() {
        windowCoordinator.showLiveTranscriptionWindow()
    }
    
    @objc func openTranscriptionHistory() {
        SettingsShellWindowController.shared.showTranscriptionHistory()
    }
    
    @objc func openAgentTask() {
        windowCoordinator.showAgentTaskCaptureWidget()
    }

    @objc func openBasilBoard() {
        DevLogger.shared.info("Opening BasilBoard from status menu", context: "StatusBarManager")
        windowCoordinator.openBasilBoard()
    }

    @objc func testKeyMonitoringAction() {
        windowCoordinator.testKeyMonitoringAction()
    }

    #if DEBUG
    @objc func triggerTrialExhaustionDebugAction() {
        TrialExhaustionManager.shared.showExhaustionAlert()
    }

    @objc func resetTrialBalanceDebugAction() {
        TrialExhaustionManager.shared.resetBalance()
    }

    @objc func triggerSetupAssistantResumeToastDebugAction() {
        (NSApp.delegate as? AppDelegate)?.triggerSetupAssistantResumeToastForDebugFromDelegate()
    }
    #endif

    // MARK: - Helper Functions
    
    // Helper function to merge three AsyncSequence streams
    @MainActor
    func merge3<T, U, V, W>(_ first: T, _ second: U, _ third: V) -> AsyncStream<W> where T: AsyncSequence, U: AsyncSequence, V: AsyncSequence, T.Element == W, U.Element == W, V.Element == W {
        return AsyncStream { continuation in
            let task1 = Task {
                do {
                    for try await element in first {
                        continuation.yield(element)
                    }
                } catch {
                    print("Error in first stream: \(error)")
                }
            }
            
            let task2 = Task {
                do {
                    for try await element in second {
                        continuation.yield(element)
                    }
                } catch {
                    print("Error in second stream: \(error)")
                }
            }
            
            let task3 = Task {
                do {
                    for try await element in third {
                        continuation.yield(element)
                    }
                } catch {
                    print("Error in third stream: \(error)")
                }
            }
            
            continuation.onTermination = { _ in
                task1.cancel()
                task2.cancel()
                task3.cancel()
            }
        }
    }
    
    // MARK: - Voice Listener State Management
    @MainActor
    private func loadInitialVoiceListenerState() async {
        do {
            let settings = try await APIClient.shared.getVoiceListenerSettings()
            isVoiceListenerEnabled = settings.voiceListenerEnabled
            
            #if DEBUG
            DevLogger.shared.info("✅ StatusBar: Loaded initial voice listener state: \(isVoiceListenerEnabled)", context: "StatusBarManager")
            #endif
            
            // Update menu with loaded state
            if let menu = statusBarItem.statusMenu {
                StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
            }
            
            // Update icon to reflect loaded voice listener state
            statusBarItem.updateIconForCurrentState()
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ StatusBar: Failed to load initial voice listener state: \(error.localizedDescription)", context: "StatusBarManager")
            #endif
            // Keep default state (false) if API call fails
        }
    }
    
    @MainActor
    private func loadInitialActivityCaptureState() async {
        await refreshActivityCaptureState()
    }

    @MainActor
    func refreshActivityCaptureState() async {
        do {
            async let settings = APIClient.shared.getActivityCaptureSettings()
            async let schedulerStatus = APIClient.shared.fetchActivityCaptureStatus()
            let (loadedSettings, loadedSchedulerStatus) = try await (settings, schedulerStatus)
            isActivityCaptureEnabled = loadedSettings.activityCaptureEnabled
            isActivityCaptureActive = loadedSchedulerStatus.isRunning

            if let menu = statusBarItem.statusMenu {
                StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
            }
            statusBarItem.updateIconForCurrentState()
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to refresh Activity Capture state: \(error.localizedDescription)", context: "StatusBarManager")
            #endif
        }
    }
    
    @MainActor
    func updateActivityCaptureEnabledState(_ enabled: Bool) {
        isActivityCaptureEnabled = enabled
        if !enabled {
            isActivityCaptureActive = false
        }
        
        // Update menu with new state
        if let menu = statusBarItem.statusMenu {
            StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
        }
        
        // Update icon to reflect new activity capture enabled state
        statusBarItem.updateIconForCurrentState()
    }
} 