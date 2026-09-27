import Foundation
import HotKey
import AppKit

extension HotkeyService {
    @MainActor
    func configureInitialHotkeys() async {
        do {
            let data = try await apiClient.get("/settings/hotkeys")
            
            // Log raw response for debugging
            if let jsonString = String(data: data, encoding: .utf8) {
                debugPrint("🔍 [DOUBLE-PRESS] Raw hotkey response from backend:")
                debugPrint(jsonString)
            }
            
            let decoder = JSONDecoder()
            let response = try decoder.decode(ServerHotkeySettingsResponse.self, from: data)
            let settings = response.settings
            
            // Convert settings response into a dictionary for configureHotkeys.
            // `get_suggestions` (legacy F9 basic suggestion) and
            // `enhanced_suggestions` (legacy F10 XML-parsed suggestion) were
            // removed during the AssistantSession unification -- both modalities now
            // live behind `assistantSession` with an in-widget speak/type
            // toggle. `capture_screen`, `insert_assistant_output`, and
            // `streaming_transcription` are pre-AssistantSession legacy holdovers
            // already inert in the server response.
            var bindings: [String: HotkeyBinding] = [:]
            bindings["transcribe_audio"] = settings.transcribe_audio
            bindings["conversation_toggle"] = settings.conversation_toggle
            bindings["assistantSession"] = settings.assistantSession
            bindings["agentTask"] = settings.agentTask
            bindings["home_board_toggle"] = settings.home_board_toggle
            
            // Log agentTask binding specifically for debugging
            debugPrint("🔍 [DOUBLE-PRESS] Decoded agentTask binding:")
            debugPrint("   key: '\(settings.agentTask.key)'")
            debugPrint("   isDoublePress: \(settings.agentTask.isDoublePress)")
            debugPrint("   doublePressKey: \(settings.agentTask.doublePressKey ?? "nil")")
            
            // Add a special binding for the Escape key (always enabled)
            let escapeKeyBinding = HotkeyBinding(
                key: "escape",
                enabled: true,
                modifiers: []
            )
            
            #if DEBUG
            DevLogger.shared.info("Setting up Escape key binding for recording cancellation", context: "HotkeyService")
            #endif
            
            // Still store the binding but with enabled=false
            bindings["cancel_recording"] = escapeKeyBinding
            
            // Check behavior settings - IMPORTANT: Restore this behavior that worked before
            let behaviorSettings = APIClient.shared.getCachedBehaviorSettings()
            if behaviorSettings.enableMonitoringAtStartup && !isEnabled {
                // Set enabled flag without requiring a toggle
                isEnabled = true
            }
            
            // Configure the hotkeys with the bindings
            configureHotkeys(with: bindings)
            
            // Always send notification after configuration is complete
            NotificationCenter.default.post(name: NSNotification.Name("HotkeyStateChanged"), object: nil)
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to configure hotkeys: \(error)", context: "HotkeyService")
            #endif
        }
    }

    @MainActor
    func configureHotkeys(with bindings: [String: HotkeyBinding]) {
        #if DEBUG
        DevLogger.shared.info("Hotkey bindings keys: \(bindings.keys.joined(separator: ", "))", context: "HotkeyService")
        #endif
        debugPrint("\n=== Configuring Hotkeys ===")
        debugPrint("Current enabled state: \(isEnabled)")
        
        // Properly clean up existing hotkeys
        hotkeys.values.forEach { hotkey in
            debugPrint("🧹 Cleaning up existing hotkey")
            hotkey.keyDownHandler = nil
            hotkey.keyUpHandler = nil
        }
        hotkeys.removeAll()
        hotkeyBindings.removeAll()  // Clear existing bindings
        
        // Clear double-press callbacks before reconfiguring
        doublePressDetector.clearAllCallbacks()
        transcriptionHotkeyGestureState.reset()
        
        // Only configure if globally enabled
        guard isEnabled else {
            debugPrint("❌ Hotkeys are globally disabled")
            return
        }
        
        configureTranscriptionHotkey(bindings["transcribe_audio"])
        configureConversationHotkey(bindings["conversation_toggle"])
        configureAssistantSessionHotkey(bindings["assistantSession"])
        configureAgentTaskHotkey(bindings["agentTask"])
        configureCancelRecordingHotkey(bindings["cancel_recording"])
        configureHomeBoardHotkey(bindings["home_board_toggle"])
    }
    
    private func configureTranscriptionHotkey(_ binding: HotkeyBinding?) {
        guard let binding = binding else { return }
        debugPrint("📝 Configuring transcription hotkey: \(binding)")
        hotkeyBindings["transcribe_audio"] = binding
        
        guard binding.enabled else {
            isTranscriptionEnabled = false
            debugPrint("❌ Transcription hotkey is disabled")
            return
        }
        
        // Check if this is a double-press modifier binding
        if binding.isDoublePress, let doublePressKeyStr = binding.doublePressKey,
           let modifierKey = ModifierKey.from(doublePressKeyStr) {
            debugPrint("📝 Configuring transcription as double-press: \(modifierKey.symbol)+\(modifierKey.symbol) (push-to-talk)")
            
            doublePressDetector.registerCallback(
                for: modifierKey,
                doublePressThreshold: 0.2,
                onDoublePress: { [weak self] (_: ModifierKey) in
                    debugPrint("\n📝 Transcription Double-Press STARTED!")
                    guard let self = self else { return }
                    guard self.shouldHandleTranscriptionHotkey() else {
                        debugPrint("❌ Transcription double-press handling prevented by debounce")
                        self.transcriptionHotkeyGestureState.reset()
                        return
                    }
                    self.handleAcceptedTranscriptionDoublePress()
                },
                onRelease: { [weak self] (_: ModifierKey, holdDuration: TimeInterval) in
                    debugPrint("\n📝 Transcription Double-Press RELEASED (held for \(String(format: "%.3f", holdDuration))s)")
                    guard let self = self else { return }
                    self.handleTranscriptionDoublePressRelease(pressDuration: holdDuration)
                }
            )
            isTranscriptionEnabled = true
            debugPrint("✅ Configured transcription hotkey (double-press with push-to-talk)")
            return
        }
        
        // Traditional modifier+key hotkey
        guard let key = Key(string: binding.key) else {
            isTranscriptionEnabled = false
            debugPrint("❌ Invalid key for transcription hotkey: '\(binding.key)'")
            return
        }
        
        debugPrint("🔑 Creating hotkey with key: \(key), modifiers: \(binding.modifiers)")
        
        let hotkey = HotKey(key: key, modifiers: binding.modifierFlags)
        
        // Single global handler for transcription hotkey
        hotkey.keyDownHandler = { [weak self] in
            debugPrint("\n⌨️ \(binding.key) PRESSED - Transcription Hotkey")
            guard let self = self else {
                debugPrint("❌ Self reference lost")
                return
            }
            
            guard self.shouldHandleTranscriptionHotkey() else {
                debugPrint("❌ Hotkey handling prevented by debounce")
                return
            }
            
            debugPrint("✅ Hotkey passed debounce check, handling transcription")
            Task { @MainActor in
                await self.handleTranscriptionHotkey()
            }
        }
        
        // Key release handler for push-to-talk
        hotkey.keyUpHandler = { [weak self] in
            debugPrint("\n⌨️ \(binding.key) RELEASED - Transcription Hotkey")
            guard let self = self else {
                debugPrint("❌ Self reference lost on key release")
                return
            }
            
            // Get press timestamp if it exists
            guard let pressTime = self.hotkeyPressTimestamps["transcribe_audio"] else {
                debugPrint("⚠️ No press timestamp found for transcription hotkey")
                return
            }
            
            let pressDuration = Date().timeIntervalSince1970 - pressTime
            self.hotkeyPressTimestamps.removeValue(forKey: "transcribe_audio")
            
            debugPrint("⏱️ Transcription hotkey held for \(String(format: "%.3f", pressDuration))s")
            debugPrint("🔧 About to create Task to call handleTranscriptionKeyRelease")
            
            Task { @MainActor in
                debugPrint("🔧 Inside Task, about to call handleTranscriptionKeyRelease")
                await self.handleTranscriptionKeyRelease(pressDuration: pressDuration)
                debugPrint("🔧 Returned from handleTranscriptionKeyRelease")
            }
        }
        
        hotkeys["transcribe_audio"] = hotkey
        isTranscriptionEnabled = true
        debugPrint("✅ Configured transcription hotkey")
    }
    
    private func configureConversationHotkey(_ binding: HotkeyBinding?) {
        guard let binding = binding else { return }
        hotkeyBindings["conversation_toggle"] = binding
        
        guard binding.enabled else {
            isConversationEnabled = false
            return
        }
        
        // Check if this is a double-press modifier binding
        if binding.isDoublePress, let doublePressKeyStr = binding.doublePressKey,
           let modifierKey = ModifierKey.from(doublePressKeyStr) {
            debugPrint("💬 Configuring conversation as double-press: \(modifierKey.symbol)+\(modifierKey.symbol)")
            
            doublePressDetector.registerCallback(for: modifierKey) { [weak self] (_: ModifierKey) in
                debugPrint("💬 Conversation Double-Press Triggered!")
                guard let self = self else { return }
                guard self.shouldHandleHotkey() else {
                    debugPrint("❌ Conversation double-press handling prevented by debounce")
                    return
                }
                Task { await self.handleConversationHotkey() }
            }
            isConversationEnabled = true
            return
        }
        
        // Traditional modifier+key hotkey
        guard let key = Key(string: binding.key) else {
            isConversationEnabled = false
            return
        }
        
        let hotkey = HotKey(key: key, modifiers: binding.modifierFlags)
        hotkey.keyDownHandler = { [weak self] in
            debugPrint("\n⌨️ \(binding.key) PRESSED - Conversation Toggle Hotkey")
            guard let self = self else {
                debugPrint("❌ Self reference lost")
                return
            }
            
            guard self.shouldHandleHotkey() else {
                debugPrint("❌ Conversation hotkey handling prevented by debounce")
                return
            }
            
            Task { await self.handleConversationHotkey() }
        }
        hotkeys["conversation_toggle"] = hotkey
        isConversationEnabled = true
    }

    private func configureHomeBoardHotkey(_ binding: HotkeyBinding?) {
        guard let binding = binding else { return }
        hotkeyBindings["home_board_toggle"] = binding

        guard binding.enabled else { return }

        if binding.isDoublePress, let doublePressKeyStr = binding.doublePressKey,
           let modifierKey = ModifierKey.from(doublePressKeyStr) {
            debugPrint("🏠 Configuring home board toggle as double-press: \(modifierKey.symbol)+\(modifierKey.symbol)")

            doublePressDetector.registerCallback(for: modifierKey) { [weak self] (_: ModifierKey) in
                debugPrint("🏠 Home Board Double-Press Triggered!")
                guard let self = self, self.shouldHandleHotkey() else { return }
                Task { await self.handleHomeBoardHotkey() }
            }
            return
        }

        guard let key = Key(string: binding.key) else { return }

        let hotkey = HotKey(key: key, modifiers: binding.modifierFlags)
        hotkey.keyDownHandler = { [weak self] in
            debugPrint("\n⌨️ \(binding.key) PRESSED - Home Board Toggle Hotkey")
            guard let self = self, self.shouldHandleHotkey() else { return }
            Task { await self.handleHomeBoardHotkey() }
        }
        hotkeys["home_board_toggle"] = hotkey
    }
    
    private func configureAssistantSessionHotkey(_ binding: HotkeyBinding?) {
        guard let binding = binding else { return }
        #if DEBUG
        DevLogger.shared.info("assistantSession binding: \(binding)", context: "HotkeyService")
        #endif
        hotkeyBindings["assistantSession"] = binding  // Always store the binding
        
        guard binding.enabled else { return }
        
        // Check if this is a double-press modifier binding
        if binding.isDoublePress, let doublePressKeyStr = binding.doublePressKey,
           let modifierKey = ModifierKey.from(doublePressKeyStr) {
            #if DEBUG
            DevLogger.shared.info("🔊 Configuring AssistantSession as double-press: \(modifierKey.symbol)+\(modifierKey.symbol)", context: "HotkeyService")
            #endif
            
            // Register double-press callback
            doublePressDetector.registerCallback(for: modifierKey) { [weak self] (_: ModifierKey) in
                #if DEBUG
                DevLogger.shared.info("🔊 AssistantSession Double-Press Triggered!", context: "HotkeyService")
                #endif
                guard let self = self else { return }
                guard self.shouldHandleHotkey() else {
                    #if DEBUG
                    DevLogger.shared.info("❌ Voice suggestion double-press handling prevented by debounce", context: "HotkeyService")
                    #endif
                    return
                }
                Task { await self.handleAssistantSessionHotkey() }
            }
            return
        }
        
        // Traditional modifier+key hotkey
        guard let key = Key(string: binding.key) else { return }
        
            let hotkey = HotKey(key: key, modifiers: binding.modifierFlags)
            hotkey.keyDownHandler = { [weak self] in
                #if DEBUG
                DevLogger.shared.info("🔊 AssistantSession Hotkey Triggered!", context: "HotkeyService")
                #endif
                guard let self = self else {
                    #if DEBUG
                    DevLogger.shared.info("❌ Self reference lost", context: "HotkeyService")
                    #endif
                    return
                }
                guard self.shouldHandleHotkey() else {
                    #if DEBUG
                    DevLogger.shared.info("❌ Voice suggestion hotkey handling prevented by debounce", context: "HotkeyService")
                    #endif
                    return
                }
                Task { await self.handleAssistantSessionHotkey() }
            }
            
            // Key release handler for push-to-talk
            hotkey.keyUpHandler = { [weak self] in
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Hotkey RELEASED", context: "HotkeyService")
                #endif
                guard let self = self else { return }
                
                guard let pressTime = self.hotkeyPressTimestamps["assistantSession"] else {
                    return
                }
                
                let pressDuration = Date().timeIntervalSince1970 - pressTime
                self.hotkeyPressTimestamps.removeValue(forKey: "assistantSession")
                
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Hotkey held for \(String(format: "%.3f", pressDuration))s", context: "HotkeyService")
                #endif
                
                Task { @MainActor in
                    await self.handleAssistantSessionKeyRelease(pressDuration: pressDuration)
                }
            }
            
            hotkeys["assistantSession"] = hotkey
    }
    
    private func configureAgentTaskHotkey(_ binding: HotkeyBinding?) {
        guard let binding = binding else { 
            debugPrint("🎤 [DOUBLE-PRESS] configureAgentTaskHotkey: binding is nil")
            return 
        }
        
        // Log ALL binding properties for debugging
        debugPrint("🎤 [DOUBLE-PRESS] agentTask binding details:")
        debugPrint("   key: '\(binding.key)'")
        debugPrint("   enabled: \(binding.enabled)")
        debugPrint("   modifiers: \(binding.modifiers)")
        debugPrint("   isDoublePress: \(binding.isDoublePress)")
        debugPrint("   doublePressKey: \(binding.doublePressKey ?? "nil")")
        
        #if DEBUG
        DevLogger.shared.info("agentTask binding: \(binding)", context: "HotkeyService")
        #endif
        hotkeyBindings["agentTask"] = binding  // Always store the binding
        
        guard binding.enabled else { 
            debugPrint("🎤 [DOUBLE-PRESS] agentTask is disabled, skipping configuration")
            return 
        }
        
        // Check if this is a double-press modifier binding
        debugPrint("🎤 [DOUBLE-PRESS] Checking for double-press: isDoublePress=\(binding.isDoublePress), doublePressKey=\(binding.doublePressKey ?? "nil")")
        
        if binding.isDoublePress, let doublePressKeyStr = binding.doublePressKey,
           let modifierKey = ModifierKey.from(doublePressKeyStr) {
            debugPrint("🎤 [DOUBLE-PRESS] ✅ Detected double-press binding! Modifier: \(modifierKey.symbol) (\(modifierKey.rawValue))")
            
            #if DEBUG
            DevLogger.shared.info("🎤 Configuring agentTask as double-press: \(modifierKey.symbol)+\(modifierKey.symbol)", context: "HotkeyService")
            #endif
            
            // Register double-press callback
            debugPrint("🎤 [DOUBLE-PRESS] Registering callback with DoublePressDetector...")
            doublePressDetector.registerCallback(for: modifierKey) { [weak self] (_: ModifierKey) in
                debugPrint("🎤 [DOUBLE-PRESS] 🎯 CALLBACK FIRED! AgentTask Double-Press Triggered!")
                #if DEBUG
                DevLogger.shared.info("🎤 AgentTask Double-Press Triggered!", context: "HotkeyService")
                #endif
                guard let self = self else { 
                    debugPrint("🎤 [DOUBLE-PRESS] ❌ self is nil in callback")
                    return 
                }
                guard self.shouldHandleHotkey() else {
                    debugPrint("🎤 [DOUBLE-PRESS] ❌ Debounced - handling prevented")
                    #if DEBUG
                    DevLogger.shared.info("❌ AgentTask double-press handling prevented by debounce", context: "HotkeyService")
                    #endif
                    return
                }
                debugPrint("🎤 [DOUBLE-PRESS] ✅ Calling handleAgentTaskHotkey()")
                Task { await self.handleAgentTaskHotkey() }
            }
            debugPrint("🎤 [DOUBLE-PRESS] Callback registered successfully")
            return
        } else {
            debugPrint("🎤 [DOUBLE-PRESS] Not a double-press binding, using traditional hotkey")
            if !binding.isDoublePress {
                debugPrint("   Reason: isDoublePress is false")
            }
            if binding.doublePressKey == nil {
                debugPrint("   Reason: doublePressKey is nil")
            }
            if let dpKey = binding.doublePressKey, ModifierKey.from(dpKey) == nil {
                debugPrint("   Reason: ModifierKey.from('\(dpKey)') returned nil")
            }
        }
        
        // Traditional modifier+key hotkey
        guard let key = Key(string: binding.key) else { return }
        
            let hotkey = HotKey(key: key, modifiers: binding.modifierFlags)
            hotkey.keyDownHandler = { [weak self] in
                #if DEBUG
                DevLogger.shared.info("🎤 AgentTask Hotkey Triggered!", context: "HotkeyService")
                #endif
                guard let self = self else {
                    #if DEBUG
                    DevLogger.shared.info("❌ Self reference lost", context: "HotkeyService")
                    #endif
                    return
                }
                
                #if DEBUG
                DevLogger.shared.info("✅ Self reference valid, calling shouldHandleHotkey", context: "HotkeyService")
                #endif
                
                guard self.shouldHandleHotkey() else {
                    #if DEBUG
                    DevLogger.shared.info("❌ AgentTask hotkey handling prevented by debounce", context: "HotkeyService")
                    #endif
                    return
                }
                
                #if DEBUG
                DevLogger.shared.info("🚀 About to create Task for handleAgentTaskHotkey", context: "HotkeyService")
                #endif
                
                Task { 
                    #if DEBUG
                    DevLogger.shared.info("🎯 Task created, calling handleAgentTaskHotkey", context: "HotkeyService")
                    #endif
                    await self.handleAgentTaskHotkey() 
                }
            }
            
            // Key release handler for push-to-talk
            hotkey.keyUpHandler = { [weak self] in
                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] Hotkey RELEASED", context: "HotkeyService")
                #endif
                guard let self = self else { return }
                
                guard let pressTime = self.hotkeyPressTimestamps["agentTask"] else {
                    return
                }
                
                let pressDuration = Date().timeIntervalSince1970 - pressTime
                self.hotkeyPressTimestamps.removeValue(forKey: "agentTask")
                
                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] Hotkey held for \(String(format: "%.3f", pressDuration))s", context: "HotkeyService")
                #endif
                
                Task { @MainActor in
                    await self.handleAgentTaskKeyRelease(pressDuration: pressDuration)
                }
            }
            
            hotkeys["agentTask"] = hotkey
    }
    
    private func configureCancelRecordingHotkey(_ binding: HotkeyBinding?) {
        guard let binding = binding else { return }
        hotkeyBindings["cancel_recording"] = binding  // Always store the binding
        
        // We don't use HotKey for Escape - we use the global monitor which checks recording state
        // This allows the Escape key to work normally in other apps when not recording
        #if DEBUG
        DevLogger.shared.info("✅ Escape key will be handled via global monitor only when recording is active", context: "HotkeyService")
        #endif
    }

    @MainActor
    func refreshBindingsWithoutConfiguring() async {
        do {
            let data = try await apiClient.get("/settings/hotkeys")
            
            let decoder = JSONDecoder()
            let response = try decoder.decode(ServerHotkeySettingsResponse.self, from: data)
            let settings = response.settings
            
            // Convert to dictionary for easier handling. See
            // `configureInitialHotkeys` for the rationale on the trimmed
            // binding set after the AssistantSession unification.
            var bindings: [String: HotkeyBinding] = [:]
            bindings["transcribe_audio"] = settings.transcribe_audio
            bindings["conversation_toggle"] = settings.conversation_toggle
            bindings["assistantSession"] = settings.assistantSession
            bindings["agentTask"] = settings.agentTask
            bindings["home_board_toggle"] = settings.home_board_toggle

            // Store the bindings in hotkeyBindings map for reference without configuring hotkeys
            self.hotkeyBindings = bindings
            
            // Post notification that hotkey bindings have changed
            NotificationCenter.default.post(name: NSNotification.Name("HotkeyBindingsChanged"), object: nil)
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to fetch hotkey display info: \(error)", context: "HotkeyService")
            #endif
        }
    }
} 