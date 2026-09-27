import Foundation
import Combine
import HotKey
import AppKit
import SwiftUI

/// Service responsible for monitoring hotkeys and communicating with the Python backend
@MainActor
final class HotkeyService: ObservableObject {
    // MARK: - Shared Instance
    static let shared = HotkeyService()
    
    // MARK: - Published Properties
    @Published var isEnabled = false
    @Published var isTranscriptionEnabled = false
    // The legacy `isCaptureEnabled` (capture_screen hotkey) and
    // `isSuggestionsEnabled` (legacy basic suggestion hotkey) state
    // flags were removed during the AssistantSession unification along with
    // their backing hotkey configuration paths. `capture_screen` was
    // already commented-out dead code and basic/enhanced suggestions
    // now live behind `assistantSession`.
    @Published var isConversationEnabled = false
    
    // AgentTask capture state
    @Published var isAgentTaskCapturing: Bool = false
    
    // MARK: - Properties
    let apiClient = APIClient.shared
    var hotkeys: [String: HotKey] = [:]
    var hotkeyBindings: [String: HotkeyBinding] = [:]  // Store the bindings for reference
    var lastHotkeyTimestamp: TimeInterval = 0
    let hotkeyDebounceInterval: TimeInterval = 0.3  // 300ms debounce
    private var isTranscriptionHotkeySuppressed = false
    var globalKeyMonitor: Any?  // Changed from private to internal - we control both sides
    var localKeyDownMonitor: Any?  // Local keyDown monitor for when Basil is focused
    
    // MARK: - Push-to-Talk Timing
    var hotkeyPressTimestamps: [String: TimeInterval] = [:]
    private var localKeyMonitor: Any?  // For keyUp events (push-to-talk release)
    
    // MARK: - AgentTask Properties
    // Dedicated AudioCaptureService instance for agentTasks (separate from AssistantSessions)
    // Initialize early with proper WebSocket context to avoid packaged build issues
    static var agentTaskAudioService: AudioCaptureService? = nil
    var agentTaskCancellables = Set<AnyCancellable>()
    
    // Dedicated monitor just for the Escape key
    var escapeKeyMonitor: Any?
    
    // Secondary backup monitor for Escape key
    var backupEscapeKeyMonitor: Any?
    
    // Direct hotkey for Escape using the HotKey library - this is what works for other hotkeys
    var escapeHotKey: HotKey?
    
    // MARK: - Double-Press Modifier Support
    /// Detector for double-press modifier key hotkeys (e.g., Option+Option)
    let doublePressDetector = DoublePressDetector()
    var transcriptionHotkeyGestureState = TranscriptionHotkeyGestureState()
    var transcriptionControllerOverride: (any TranscriptionHotkeyControlling)?
    
    // MARK: - Suspension Support
    /// Whether hotkey listeners are currently suspended (for recording)
    private var isSuspended: Bool = false
    /// Stored bindings during suspension (to restore after)
    private var suspendedBindings: [String: HotkeyBinding] = [:]
    
    // MARK: - Initialization
    init() {
        #if DEBUG
        DevLogger.shared.info("Initializing HotkeyService", context: "HotkeyService")
        #endif
        
        // Don't configure hotkeys immediately - wait for backend availability
        // This will be handled by configureHotkeysWhenBackendReady() if needed
        Task { @MainActor in
            #if DEBUG
            DevLogger.shared.info("HotkeyService initialized, waiting for explicit configuration", context: "HotkeyService")
            #endif
        }
        
        // Listen for recording state changes to know when to handle Escape key
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleRecordingStateChange),
            name: NSNotification.Name("RecordingStateChanged"),
            object: nil
        )
        
        // Setup global key monitor to detect the Escape key during recording
        setupGlobalKeyMonitor()
        
        // Setup key release monitoring for push-to-talk
        setupKeyReleaseMonitoring()
        
        // Initialize agentTask audio service early to avoid packaged build issues  
        Task { @MainActor in
            initializeAgentTaskAudioService()
        }
    }
    
    // Initialize agentTask audio service early to avoid packaged build issues
    @MainActor
    private func initializeAgentTaskAudioService() {
        guard HotkeyService.agentTaskAudioService == nil else { return }
        
        #if DEBUG
        DevLogger.shared.info("[AGENT_TASK] 🎙️ Initializing agentTask AudioCaptureService during HotkeyService startup", context: "HotkeyService")
        #endif
        
        // Initialize with WebSocket service to ensure proper context in packaged builds
        HotkeyService.agentTaskAudioService = AudioCaptureService(webSocketService: WebSocketService.shared)
        
        #if DEBUG
        DevLogger.shared.info("[AGENT_TASK] ✅ AgentTask AudioCaptureService initialized during startup", context: "HotkeyService")
        #endif
    }
    
    /// Waits for backend to become available, then configures hotkeys
    @MainActor 
    func configureHotkeysWhenBackendReady() async {
        let maxWaitTime: TimeInterval = 30.0 // 30 second timeout
        let checkInterval: TimeInterval = 0.5 // Check every 500ms
        let startTime = Date()
        
        #if DEBUG
        DevLogger.shared.info("🔄 STARTUP: Waiting for backend availability to configure hotkeys (timeout: \(maxWaitTime)s)...", context: "HotkeyService")
        #endif
        
        while Date().timeIntervalSince(startTime) < maxWaitTime {
            if APIClient.shared.isBackendAvailable {
                #if DEBUG
                DevLogger.shared.info("✅ STARTUP: Backend is now available. Configuring hotkeys...", context: "HotkeyService")
                #endif
                
                await configureInitialHotkeys()
                return
            }
            
            // Wait before next check
            try? await Task.sleep(nanoseconds: UInt64(checkInterval * 1_000_000_000))
        }
        
        #if DEBUG
        DevLogger.shared.error("⏰ STARTUP: Timeout waiting for backend availability (\(maxWaitTime)s). Hotkeys not configured.", context: "HotkeyService")
        #endif
    }
    
    // MARK: - Methods
    @MainActor
    func toggleHotkeys() {
        isEnabled.toggle()
        if isEnabled {
            #if DEBUG
            DevLogger.shared.info("Enabling global key monitoring", context: "HotkeyService")
            #endif
            setupGlobalKeyMonitor()
            Task {
                await configureInitialHotkeys()
            }
        } else {
            #if DEBUG
            DevLogger.shared.info("Disabling global key monitoring", context: "HotkeyService")
            #endif
            removeGlobalKeyMonitor()
            disableAllHotkeys()
            
            // Also clean up any escape key handlers
            cleanupEscapeKeyHandlers()
            
            // Keep the bindings visible in the menu even when hotkeys are disabled
            Task {
                // Fetch the latest bindings to ensure they're up to date
                await refreshBindingsWithoutConfiguring()
            }
        }
        
        // Post notification that hotkey state has changed so UI can update
        NotificationCenter.default.post(name: NSNotification.Name("HotkeyStateChanged"), object: nil)
        
        // Also post a notification specifically for the status bar icon
        NotificationCenter.default.post(name: NSNotification.Name("UpdateStatusBarIcon"), object: ["enabled": isEnabled])
    }
    
    @MainActor
    func refreshHotkeys() async {
        if isEnabled {
            await configureInitialHotkeys()
        }
        // Settings surfaces need this reconciliation signal even when global
        // monitoring is disabled; the persisted binding may still have
        // changed through the native or React settings window.
        NotificationCenter.default.post(name: NSNotification.Name("HotkeyStateChanged"), object: nil)
    }
    
    /// Temporarily suspend all hotkey listeners to prevent triggering actions during recording
    @MainActor
    func suspendListeners() {
        guard !isSuspended else { return }
        
        isSuspended = true
        
        // Store current bindings for restoration
        suspendedBindings = hotkeyBindings
        
        // Suspend double-press detector
        doublePressDetector.suspendMonitoring()
        
        // Disable all HotKey handlers by clearing them
        hotkeys.values.forEach { hotkey in
            hotkey.keyDownHandler = nil
            hotkey.keyUpHandler = nil
        }
        
        #if DEBUG
        DevLogger.shared.info("Hotkey listeners suspended", context: "HotkeyService")
        #endif
    }
    
    /// Resume hotkey listeners after recording
    @MainActor
    func resumeListeners() {
        guard isSuspended else { return }
        
        isSuspended = false
        
        // Resume double-press detector
        doublePressDetector.resumeMonitoring()
        
        // Restore hotkeys if we have stored bindings and service is enabled
        if !suspendedBindings.isEmpty && isEnabled {
            configureHotkeys(with: suspendedBindings)
        }
        
        // Clear stored bindings
        suspendedBindings.removeAll()
        
        #if DEBUG
        DevLogger.shared.info("Hotkey listeners resumed", context: "HotkeyService")
        #endif
    }
    
    @MainActor
    func disableAllHotkeys() {
        hotkeys.removeAll()
        isTranscriptionEnabled = false
        isConversationEnabled = false

        // Also clear double-press callbacks
        doublePressDetector.clearAllCallbacks()
    }
    
    @MainActor
    func shouldHandleHotkey() -> Bool {
        #if DEBUG
        DevLogger.shared.info("🔍 shouldHandleHotkey() called", context: "HotkeyService")
        #endif
        
        let now = Date().timeIntervalSince1970
        let timeSinceLastPress = now - lastHotkeyTimestamp
        
        debugPrint("⏱️ Time since last hotkey press: \(timeSinceLastPress)s")
        
        if timeSinceLastPress < hotkeyDebounceInterval {
            debugPrint("🚫 Debouncing hotkey press (too soon after last press)")
            #if DEBUG
            DevLogger.shared.info("🚫 Hotkey debounced", context: "HotkeyService")
            #endif
            return false
        }
        
        debugPrint("✅ Hotkey press allowed")
        #if DEBUG
        DevLogger.shared.info("✅ Hotkey allowed by shouldHandleHotkey", context: "HotkeyService")
        #endif
        lastHotkeyTimestamp = now
        return true
    }

    @MainActor
    func beginTranscriptionHotkeySuppression() {
        isTranscriptionHotkeySuppressed = true
        transcriptionHotkeyGestureState.reset()
    }

    @MainActor
    func endTranscriptionHotkeySuppression() {
        isTranscriptionHotkeySuppressed = false
        transcriptionHotkeyGestureState.reset()
    }

    @MainActor
    func shouldHandleTranscriptionHotkey() -> Bool {
        guard !isTranscriptionHotkeySuppressed else {
            transcriptionHotkeyGestureState.reset()
            return false
        }
        return shouldHandleHotkey()
    }
    
    @MainActor
    func setupGlobalKeyMonitor() {
        // Check Input Monitoring permission first
        if !checkInputMonitoringPermission() {
            #if DEBUG
            DevLogger.shared.warning("❌ Input Monitoring permission not granted - hotkeys will not work", context: "HotkeyService")
            #endif
            requestInputMonitoringPermission()
            return
        }
        
        // Remove existing monitors if any
        if let monitor = globalKeyMonitor {
            NSEvent.removeMonitor(monitor)
            globalKeyMonitor = nil
        }
        if let monitor = localKeyDownMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyDownMonitor = nil
        }
        
        #if DEBUG
        DevLogger.shared.info("Setting up key monitors (global + local)", context: "HotkeyService")
        #endif
        
        // Create new monitor for key down events - but NOT handling Escape key
        // Escape key will be handled by HotKey library during recording
        let eventMask: NSEvent.EventTypeMask = [.keyDown]
        
        // GLOBAL monitor: keyDown events when OTHER apps are focused
        globalKeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: eventMask) { event in
            // We have a dedicated handler for Escape key now, so skip it in the global monitor
            if event.keyCode == 53 {
                return
            }
            
            // Normal handling for other keys continues below...
            
            // Get modifier flags
            let modifiers = event.modifierFlags
            var modifierStrings: [String] = []
            if modifiers.contains(.command) { modifierStrings.append("⌘") }
            if modifiers.contains(.option) { modifierStrings.append("⌥") }
            if modifiers.contains(.control) { modifierStrings.append("⌃") }
            if modifiers.contains(.shift) { modifierStrings.append("⇧") }
            
            // We monitor but don't actually handle other keys here - that's done by HotKey library
        }
        
        // LOCAL monitor: keyDown events when BASIL is focused
        // This fixes hotkeys not working when Basil windows are active
        localKeyDownMonitor = NSEvent.addLocalMonitorForEvents(matching: eventMask) { event in
            // Skip Escape key - handled by HotKey library
            if event.keyCode == 53 {
                return event
            }
            
            // Get modifier flags for logging/monitoring
            let modifiers = event.modifierFlags
            var modifierStrings: [String] = []
            if modifiers.contains(.command) { modifierStrings.append("⌘") }
            if modifiers.contains(.option) { modifierStrings.append("⌥") }
            if modifiers.contains(.control) { modifierStrings.append("⌃") }
            if modifiers.contains(.shift) { modifierStrings.append("⇧") }
            
            // Pass event through - actual handling done by HotKey library
            return event
        }
        
        #if DEBUG
        DevLogger.shared.info("Key monitor state: global=\(globalKeyMonitor != nil), local=\(localKeyDownMonitor != nil)", context: "HotkeyService")
        #endif
    }
    
    @MainActor
    func removeGlobalKeyMonitor() {
        if let monitor = globalKeyMonitor {
            NSEvent.removeMonitor(monitor)
            globalKeyMonitor = nil
        }
        if let monitor = localKeyDownMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyDownMonitor = nil
        }
    }
    
    // MARK: - Push-to-Talk Key Release Monitoring
    
    @MainActor
    func setupKeyReleaseMonitoring() {
        // Remove existing monitor
        if let monitor = localKeyMonitor {
            NSEvent.removeMonitor(monitor)
        }
        
        #if DEBUG
        DevLogger.shared.info("Setting up key release monitoring for push-to-talk", context: "HotkeyService")
        #endif
        
        // Monitor local key up events
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyUp) { [weak self] event in
            Task { @MainActor in
                await self?.handleKeyRelease(event)
            }
            return event
        }
        
        #if DEBUG
        DevLogger.shared.info("Key release monitor state: \(localKeyMonitor != nil ? "ACTIVE" : "FAILED")", context: "HotkeyService")
        #endif
    }
    
    @MainActor
    private func handleKeyRelease(_ event: NSEvent) async {
        let keyCode = event.keyCode
        let modifiers = event.modifierFlags
        
        // Check if this matches the transcription hotkey
        if let transcriptionBinding = hotkeyBindings["transcribe_audio"],
           transcriptionBinding.enabled,
           matchesBinding(keyCode: keyCode, modifiers: modifiers, binding: transcriptionBinding),
           let pressTime = hotkeyPressTimestamps["transcribe_audio"] {
            
            let pressDuration = Date().timeIntervalSince1970 - pressTime
            hotkeyPressTimestamps.removeValue(forKey: "transcribe_audio")
            
            #if DEBUG
            DevLogger.shared.info("Transcription hotkey released after \(String(format: "%.3f", pressDuration))s", context: "HotkeyService")
            #endif
            
            await handleTranscriptionKeyRelease(pressDuration: pressDuration)
        }
        
        // Check if this matches the agentTask hotkey
        if let agentTaskBinding = hotkeyBindings["agentTask"],
           agentTaskBinding.enabled,
           matchesBinding(keyCode: keyCode, modifiers: modifiers, binding: agentTaskBinding),
           let pressTime = hotkeyPressTimestamps["agentTask"] {
            
            let pressDuration = Date().timeIntervalSince1970 - pressTime
            hotkeyPressTimestamps.removeValue(forKey: "agentTask")
            
            #if DEBUG
            DevLogger.shared.info("AgentTask hotkey released after \(String(format: "%.3f", pressDuration))s", context: "HotkeyService")
            #endif
            
            await handleAgentTaskKeyRelease(pressDuration: pressDuration)
        }
        
        // Check if this matches the AssistantSession hotkey
        if let assistantSessionBinding = hotkeyBindings["assistantSession"],
           assistantSessionBinding.enabled,
           matchesBinding(keyCode: keyCode, modifiers: modifiers, binding: assistantSessionBinding),
           let pressTime = hotkeyPressTimestamps["assistantSession"] {
            
            let pressDuration = Date().timeIntervalSince1970 - pressTime
            hotkeyPressTimestamps.removeValue(forKey: "assistantSession")
            
            #if DEBUG
            DevLogger.shared.info("Voice suggestion hotkey released after \(String(format: "%.3f", pressDuration))s", context: "HotkeyService")
            #endif
            
            await handleAssistantSessionKeyRelease(pressDuration: pressDuration)
        }
    }
    
    private func matchesBinding(keyCode: UInt16, modifiers: NSEvent.ModifierFlags, binding: HotkeyBinding) -> Bool {
        // Convert binding key to keyCode
        guard let key = Key(string: binding.key) else { return false }
        if key.carbonKeyCode != keyCode { return false }
        
        // Check modifiers
        let hasCommand = modifiers.contains(.command)
        let hasOption = modifiers.contains(.option)
        let hasControl = modifiers.contains(.control)
        let hasShift = modifiers.contains(.shift)
        
        let needsCommand = binding.modifiers.contains("command") || binding.modifiers.contains("cmd")
        let needsOption = binding.modifiers.contains("option") || binding.modifiers.contains("alt")
        let needsControl = binding.modifiers.contains("control") || binding.modifiers.contains("ctrl")
        let needsShift = binding.modifiers.contains("shift")
        
        return hasCommand == needsCommand &&
               hasOption == needsOption &&
               hasControl == needsControl &&
               hasShift == needsShift
    }
    
    func recordHotkeyPress(hotkeyId: String) {
        hotkeyPressTimestamps[hotkeyId] = Date().timeIntervalSince1970
        #if DEBUG
        DevLogger.shared.info("Recorded press time for \(hotkeyId)", context: "HotkeyService")
        #endif
    }
    
    deinit {
        // Since deinit can't be async, we need to handle actor isolation differently
        
        // For monitors, we can safely clean them up directly
        if let monitor = globalKeyMonitor {
            NSEvent.removeMonitor(monitor)
            globalKeyMonitor = nil
        }
        
        // For localKeyDownMonitor - handle directly
        if let monitor = localKeyDownMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyDownMonitor = nil
        }
        
        // For escapeKeyMonitor - handle directly
        if let monitor = escapeKeyMonitor {
            NSEvent.removeMonitor(monitor)
            escapeKeyMonitor = nil
        }
        
        // For backupEscapeKeyMonitor - handle directly
        if let monitor = backupEscapeKeyMonitor {
            NSEvent.removeMonitor(monitor)
            backupEscapeKeyMonitor = nil
        }
        
        // For localKeyMonitor (push-to-talk) - handle directly
        if let monitor = localKeyMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyMonitor = nil
        }
        
        // For HotKey objects - clean up handlers
        escapeHotKey?.keyDownHandler = nil
        escapeHotKey?.keyUpHandler = nil
        escapeHotKey = nil
        
        // Note: DoublePressDetector has its own deinit that handles cleanup
        // when this HotkeyService instance is deallocated
        
        // Remove notification observers
        NotificationCenter.default.removeObserver(
            self,
            name: NSNotification.Name("RecordingStateChanged"),
            object: nil
        )
    }
    
    // MARK: - Permission Checking
    private func checkInputMonitoringPermission() -> Bool {
        // Test if we can create a global event monitor (this requires Input Monitoring permission)
        let testMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown]) { _ in }
        
        if testMonitor != nil {
            NSEvent.removeMonitor(testMonitor!)
            return true
        } else {
            return false
        }
    }
    
    private func requestInputMonitoringPermission() {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.messageText = "Input Monitoring Permission Required"
            alert.informativeText = """
            Basil needs Input Monitoring permission to detect global hotkeys.
            
            Please grant permission in:
            System Settings > Privacy & Security > Input Monitoring
            
            After granting permission, restart Basil for changes to take effect.
            """
            alert.alertStyle = .warning
            alert.addButton(withTitle: "Open System Settings")
            alert.addButton(withTitle: "Continue Without Hotkeys")
            
            let response = alert.runModal()
            
            if response == .alertFirstButtonReturn {
                // Open System Settings to Input Monitoring
                if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent") {
                    NSWorkspace.shared.open(url)
                }
            }
        }
    }
} 