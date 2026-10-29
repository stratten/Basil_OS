import Foundation
import AppKit

/// Modifier keys that can be detected for double-press
public enum ModifierKey: String, CaseIterable, Sendable {
    case option = "option"
    case command = "command"
    case control = "control"
    case shift = "shift"
    
    /// The corresponding NSEvent.ModifierFlags for this key
    public var flag: NSEvent.ModifierFlags {
        switch self {
        case .option: return .option
        case .command: return .command
        case .control: return .control
        case .shift: return .shift
        }
    }
    
    /// Display symbol for this modifier
    public var symbol: String {
        switch self {
        case .option: return "⌥"
        case .command: return "⌘"
        case .control: return "⌃"
        case .shift: return "⇧"
        }
    }
    
    /// Create from string (case-insensitive, supports aliases)
    public static func from(_ string: String) -> ModifierKey? {
        switch string.lowercased() {
        case "option", "alt": return .option
        case "command", "cmd": return .command
        case "control", "ctrl": return .control
        case "shift": return .shift
        default: return nil
        }
    }
}

/// Callback type for double-press detection
public typealias DoublePressCallback = (ModifierKey) -> Void

/// Callback type for release after double-press (receives modifier key and hold duration)
public typealias DoublePressReleaseCallback = (ModifierKey, TimeInterval) -> Void

/// Detects quick double-presses of modifier keys (e.g., Option+Option)
/// Uses NSEvent.flagsChanged monitoring to track modifier key state changes
/// Supports push-to-talk: tracks hold state after double-press and fires release callback
@MainActor
final class DoublePressDetector {
    // MARK: - Configuration
    
    /// Maximum time between presses to count as a double-press (in seconds)
    var doublePressThreshold: TimeInterval = 0.3

    /// Per-binding overrides keep one sensitive modifier hotkey from changing
    /// the recognition window of every other double-press binding.
    private var doublePressThresholds: [ModifierKey: TimeInterval] = [:]
    
    // MARK: - State
    
    /// Last press timestamp for each modifier key
    private var lastPressTimestamps: [ModifierKey: TimeInterval] = [:]
    
    /// Previous modifier flags state (to detect press vs release)
    private var previousModifierFlags: NSEvent.ModifierFlags = []
    
    /// Global event monitor for flags changed events (when OTHER apps are focused)
    /// Using nonisolated(unsafe) to allow access from deinit
    nonisolated(unsafe) private var globalFlagsMonitor: Any?
    
    /// Local event monitor for flags changed events (when BASIL is focused)
    /// Using nonisolated(unsafe) to allow access from deinit
    nonisolated(unsafe) private var localFlagsMonitor: Any?
    
    /// Registered callbacks for each modifier key (fired on double-press)
    private var callbacks: [ModifierKey: DoublePressCallback] = [:]
    
    /// Registered release callbacks for each modifier key (fired when released after double-press)
    private var releaseCallbacks: [ModifierKey: DoublePressReleaseCallback] = [:]
    
    /// Active double-press holds: tracks when double-press started for push-to-talk
    /// If a modifier is in this dictionary, we're in "holding" state after double-press
    private var activeDoublePresses: [ModifierKey: TimeInterval] = [:]
    
    /// Whether the detector is currently active
    private(set) var isActive: Bool = false
    
    /// Whether monitoring is currently suspended (temporarily paused)
    private var isSuspended: Bool = false
    
    // MARK: - Initialization
    
    init() {
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Initialized", context: "Hotkeys")
        #endif
    }
    
    deinit {
        // Clean up monitors - note: this needs to happen on the main thread
        // but since we're @MainActor this should be fine
        if let monitor = globalFlagsMonitor {
            NSEvent.removeMonitor(monitor)
        }
        if let monitor = localFlagsMonitor {
            NSEvent.removeMonitor(monitor)
        }
    }
    
    // MARK: - Public API
    
    /// Register callbacks for when a modifier key is double-pressed and optionally released
    /// - Parameters:
    ///   - modifierKey: The modifier key to track (option, command, control, shift)
    ///   - onDoublePress: Called when double-press is detected
    ///   - onRelease: Optional callback when modifier is released after double-press (for push-to-talk)
    func registerCallback(
        for modifierKey: ModifierKey,
        doublePressThreshold: TimeInterval? = nil,
        onDoublePress: @escaping DoublePressCallback,
        onRelease: DoublePressReleaseCallback? = nil
    ) {
        callbacks[modifierKey] = onDoublePress
        if let doublePressThreshold {
            doublePressThresholds[modifierKey] = doublePressThreshold
        } else {
            doublePressThresholds.removeValue(forKey: modifierKey)
        }
        if let releaseCallback = onRelease {
            releaseCallbacks[modifierKey] = releaseCallback
        }
        
        debugPrint("🔍 [DoublePressDetector] Registered callback for \(modifierKey.symbol) (\(modifierKey.rawValue))")
        debugPrint("🔍 [DoublePressDetector] Total callbacks registered: \(callbacks.count), release callbacks: \(releaseCallbacks.count)")
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Registered callback for \(modifierKey.symbol) (hasRelease: \(onRelease != nil))", context: "Hotkeys")
        #endif
        
        // Start monitoring if not already active
        if !isActive {
            debugPrint("🔍 [DoublePressDetector] Not active, starting monitoring...")
            startMonitoring()
        } else {
            debugPrint("🔍 [DoublePressDetector] Already active, no need to start monitoring")
        }
    }
    
    /// Unregister callbacks for a modifier key
    func unregisterCallback(for modifierKey: ModifierKey) {
        callbacks.removeValue(forKey: modifierKey)
        releaseCallbacks.removeValue(forKey: modifierKey)
        doublePressThresholds.removeValue(forKey: modifierKey)
        activeDoublePresses.removeValue(forKey: modifierKey)
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Unregistered callback for \(modifierKey.rawValue)", context: "Hotkeys")
        #endif
        
        // Stop monitoring if no callbacks remain
        if callbacks.isEmpty {
            stopMonitoring()
        }
    }
    
    /// Clear all registered callbacks
    func clearAllCallbacks() {
        callbacks.removeAll()
        releaseCallbacks.removeAll()
        doublePressThresholds.removeAll()
        activeDoublePresses.removeAll()
        stopMonitoring()
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Cleared all callbacks", context: "Hotkeys")
        #endif
    }
    
    /// Temporarily suspend event handling without stopping monitors
    /// Used when recording hotkeys to prevent triggering actions
    func suspendMonitoring() {
        guard !isSuspended else { return }
        isSuspended = true
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Suspended monitoring", context: "Hotkeys")
        #endif
    }
    
    /// Resume event handling after suspension
    func resumeMonitoring() {
        guard isSuspended else { return }
        isSuspended = false
        // Reset state to avoid stale press detection
        lastPressTimestamps.removeAll()
        previousModifierFlags = []
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Resumed monitoring", context: "Hotkeys")
        #endif
    }
    
    /// Start monitoring for modifier key changes
    func startMonitoring() {
        guard !isActive else { 
            debugPrint("🔍 [DoublePressDetector] startMonitoring called but already active")
            return 
        }
        
        debugPrint("🔍 [DoublePressDetector] Starting flags change monitoring...")
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Starting flags change monitoring", context: "Hotkeys")
        #endif
        
        // GLOBAL monitor: flagsChanged events when OTHER apps are focused
        globalFlagsMonitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            // Dispatch to main actor since we're in a callback
            Task { @MainActor in
                self?.handleFlagsChanged(event)
            }
        }
        
        // LOCAL monitor: flagsChanged events when BASIL is focused
        // This fixes hotkeys not working when Basil windows are active
        localFlagsMonitor = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            // Dispatch to main actor since we're in a callback
            Task { @MainActor in
                self?.handleFlagsChanged(event)
            }
            return event  // Pass event through (don't consume it)
        }
        
        isActive = (globalFlagsMonitor != nil || localFlagsMonitor != nil)
        
        debugPrint("🔍 [DoublePressDetector] Monitoring state: global=\(globalFlagsMonitor != nil), local=\(localFlagsMonitor != nil)")
        if globalFlagsMonitor == nil {
            debugPrint("🔍 [DoublePressDetector] ⚠️ FAILED to create global monitor - check Input Monitoring permissions!")
        }
        if localFlagsMonitor == nil {
            debugPrint("🔍 [DoublePressDetector] ⚠️ FAILED to create local monitor")
        }
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Monitoring state: global=\(globalFlagsMonitor != nil), local=\(localFlagsMonitor != nil)", context: "Hotkeys")
        #endif
    }
    
    /// Stop monitoring for modifier key changes
    func stopMonitoring() {
        guard isActive else { return }
        
        // Remove global monitor
        if let monitor = globalFlagsMonitor {
            NSEvent.removeMonitor(monitor)
            globalFlagsMonitor = nil
        }
        
        // Remove local monitor
        if let monitor = localFlagsMonitor {
            NSEvent.removeMonitor(monitor)
            localFlagsMonitor = nil
        }
        
        isActive = false
        
        // Reset state
        lastPressTimestamps.removeAll()
        previousModifierFlags = []
        activeDoublePresses.removeAll()
        
        #if DEBUG
        DevLogger.shared.info("[DoublePressDetector] Stopped monitoring", context: "Hotkeys")
        #endif
    }
    
    // MARK: - Event Handling
    
    private func handleFlagsChanged(_ event: NSEvent) {
        // If suspended, ignore all events
        guard !isSuspended else { return }
        
        let currentFlags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        let now = Date().timeIntervalSince1970
        
        // Log every flags change event (but only if we have callbacks registered)
        if !callbacks.isEmpty {
            debugPrint("🔍 [DoublePressDetector] flagsChanged event received")
            debugPrint("   previousFlags: \(describeFlagsState(previousModifierFlags))")
            debugPrint("   currentFlags: \(describeFlagsState(currentFlags))")
            debugPrint("   registered callbacks for: \(callbacks.keys.map { $0.symbol }.joined(separator: ", "))")
            if !activeDoublePresses.isEmpty {
                debugPrint("   active holds: \(activeDoublePresses.keys.map { $0.symbol }.joined(separator: ", "))")
            }
        }
        
        // Check each modifier key we're tracking
        for modifierKey in ModifierKey.allCases {
            guard callbacks[modifierKey] != nil else { continue }
            
            let wasPressed = previousModifierFlags.contains(modifierKey.flag)
            let isPressed = currentFlags.contains(modifierKey.flag)
            
            // Detect key press (transition from not pressed to pressed)
            if !wasPressed && isPressed {
                debugPrint("🔍 [DoublePressDetector] \(modifierKey.symbol) KEY DOWN detected")
                handleModifierPress(modifierKey, at: now)
            } else if wasPressed && !isPressed {
                debugPrint("🔍 [DoublePressDetector] \(modifierKey.symbol) KEY UP detected")
                handleModifierRelease(modifierKey, at: now)
            }
        }
        
        // Update previous state
        previousModifierFlags = currentFlags
    }
    
    private func handleModifierRelease(_ modifierKey: ModifierKey, at timestamp: TimeInterval) {
        // Check if we're in an active double-press hold for this modifier
        guard let startTime = activeDoublePresses[modifierKey] else {
            return // Not in a double-press hold, ignore
        }
        
        let holdDuration = timestamp - startTime
        debugPrint("🔍 [DoublePressDetector] 🏁 RELEASE after double-press: \(modifierKey.symbol) (held for \(String(format: "%.3f", holdDuration))s)")
        
        // Clear the active hold state
        activeDoublePresses.removeValue(forKey: modifierKey)
        
        // Fire the release callback if one is registered
        if let releaseCallback = releaseCallbacks[modifierKey] {
            debugPrint("🔍 [DoublePressDetector] Firing release callback for \(modifierKey.symbol)...")
            releaseCallback(modifierKey, holdDuration)
            debugPrint("🔍 [DoublePressDetector] Release callback fired successfully")
        } else {
            debugPrint("🔍 [DoublePressDetector] No release callback registered for \(modifierKey.symbol)")
        }
    }
    
    /// Helper to describe modifier flags for logging
    private func describeFlagsState(_ flags: NSEvent.ModifierFlags) -> String {
        var parts: [String] = []
        if flags.contains(.option) { parts.append("⌥") }
        if flags.contains(.command) { parts.append("⌘") }
        if flags.contains(.control) { parts.append("⌃") }
        if flags.contains(.shift) { parts.append("⇧") }
        return parts.isEmpty ? "(none)" : parts.joined(separator: "+")
    }
    
    private func handleModifierPress(_ modifierKey: ModifierKey, at timestamp: TimeInterval) {
        // Check if we have a previous press within the threshold
        if let lastPress = lastPressTimestamps[modifierKey] {
            let timeDelta = timestamp - lastPress
            let threshold = doublePressThresholds[modifierKey] ?? doublePressThreshold
            
            debugPrint("🔍 [DoublePressDetector] Checking for double-press: timeDelta=\(String(format: "%.3f", timeDelta))s, threshold=\(threshold)s")
            
            if timeDelta <= threshold {
                // Double-press detected!
                debugPrint("🔍 [DoublePressDetector] 🎯🎯🎯 DOUBLE-PRESS DETECTED: \(modifierKey.symbol)+\(modifierKey.symbol)!")
                #if DEBUG
                DevLogger.shared.info("[DoublePressDetector] 🎯 Double-press detected: \(modifierKey.symbol)+\(modifierKey.symbol) (delta: \(String(format: "%.3f", timeDelta))s)", context: "Hotkeys")
                #endif
                
                // Clear the timestamp to prevent triple-press from triggering again
                lastPressTimestamps.removeValue(forKey: modifierKey)
                
                // Track active hold state for push-to-talk (if release callback is registered)
                if releaseCallbacks[modifierKey] != nil {
                    activeDoublePresses[modifierKey] = timestamp
                    debugPrint("🔍 [DoublePressDetector] Started tracking hold for \(modifierKey.symbol) (push-to-talk mode)")
                }
                
                // Fire the callback
                if let callback = callbacks[modifierKey] {
                    debugPrint("🔍 [DoublePressDetector] Firing callback for \(modifierKey.symbol)...")
                    callback(modifierKey)
                    debugPrint("🔍 [DoublePressDetector] Callback fired successfully")
                } else {
                    debugPrint("🔍 [DoublePressDetector] ⚠️ No callback found for \(modifierKey.symbol)")
                }
                
                return
            } else {
                debugPrint("🔍 [DoublePressDetector] Time delta too large (\(String(format: "%.3f", timeDelta))s > \(threshold)s), recording as new first press")
            }
        } else {
            debugPrint("🔍 [DoublePressDetector] First press of \(modifierKey.symbol), recording timestamp")
        }
        
        // Record this press for potential double-press detection
        lastPressTimestamps[modifierKey] = timestamp
        
        #if DEBUG
        DevLogger.shared.debug("[DoublePressDetector] Recorded \(modifierKey.symbol) press at \(timestamp)", context: "Hotkeys")
        #endif
    }
}
