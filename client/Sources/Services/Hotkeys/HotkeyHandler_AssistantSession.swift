import Foundation
import AppKit
import Combine

extension HotkeyService {
    @MainActor
    func handleAssistantSessionHotkey() async {
        // Record press time for push-to-talk
        recordHotkeyPress(hotkeyId: "assistantSession")
        
        // Check if widget is visible and in completed state (refinement scenario)
        if let vm = AssistantSessionWindowController.sharedController?.viewModel {
            
            // Case 1: Widget visible and recording - stop recording
            if vm.isRecording {
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Widget recording - stopping recording", context: "HotkeyService")
                #endif
                vm.stopRecording()
                return
            }
            
            // Case 2: Widget visible with completed AssistantSession output - check if refinement is possible
            if vm.assistantSessionStatus == .completed && !vm.isRefinementMode {
                // CRITICAL: Only enter refinement mode if widget persistence is enabled
                // If closeAssistantSessionOnInsert is true, widget should have auto-closed already
                // But check the setting to be safe
                do {
                    let settingsData = try await APIClient.shared.get("/settings/models")
                    let decoder = JSONDecoder()
                    decoder.keyDecodingStrategy = .convertFromSnakeCase
                    struct ResponseWrapper: Codable { let status: String; let settings: ReasoningSettingsModel }
                    let response = try decoder.decode(ResponseWrapper.self, from: settingsData)

                    if response.settings.closeAssistantSessionOnInsert {
                        // User has auto-close enabled - should not be in refinement scenario
                        // Treat as new session request
                        #if DEBUG
                        DevLogger.shared.info("[ASSISTANT_SESSION] Auto-close enabled but widget visible - starting new session", context: "HotkeyService")
                        #endif
                        await startNewAssistantSessionSession()
                        return
                    } else {
                        // Widget persistence enabled - proceed with refinement
                        #if DEBUG
                        DevLogger.shared.info("[ASSISTANT_SESSION] Widget completed with persistence enabled - entering refinement mode", context: "HotkeyService")
                        #endif
                        vm.enterRefinementMode()
                        await vm.startRefinementRecording()
                        return
                    }
                } catch {
                    // Fallback: treat as refinement if widget is visible and completed
                    #if DEBUG
                    DevLogger.shared.warning("[ASSISTANT_SESSION] Could not check settings, defaulting to refinement mode", context: "HotkeyService")
                    #endif
                    vm.enterRefinementMode()
                    await vm.startRefinementRecording()
                    return
                }
            }
            
            // Case 3: Widget in refinement mode and ready - start refinement recording
            if vm.isRefinementMode && !vm.isRecording {
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Starting refinement recording", context: "HotkeyService")
                #endif
                await vm.startRefinementRecording()
                return
            }
        }
        
        // Case 4: No widget or widget not in refinement state - start new session
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] Starting new AssistantSession session", context: "HotkeyService")
        #endif
        await startNewAssistantSessionSession()
    }
    
    private func startNewAssistantSessionSession() async {
        // CRITICAL: Detect text selection BEFORE showing widget to avoid focus stealing issues
        // The widget may change focus, so we must capture selection while the source app is still focused
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] 🔍 Starting text selection detection (BEFORE widget shown)...", context: "HotkeyService")
        #endif
        
        let textSelectionService = TextSelectionService()
        let selectionResult = await textSelectionService.detectTextSelection()
        
        if selectionResult.hasSelection {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] ✅ Text selection CAPTURED successfully!", context: "HotkeyService")
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] App: \(selectionResult.applicationName)", context: "HotkeyService")
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Selection length: \(selectionResult.selectedText.count) chars", context: "HotkeyService")
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Selection preview: '\(selectionResult.selectedText.prefix(50))'...", context: "HotkeyService")
            if selectionResult.selectedText.count > 50 {
                DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Selection ending: '...'\(selectionResult.selectedText.suffix(50))'", context: "HotkeyService")
            }
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Confidence: \(selectionResult.confidence)", context: "HotkeyService")
            #endif
        } else {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] ℹ️ No text selection detected - will proceed with full document mode", context: "HotkeyService")
            #endif
        }
        
        // Check if region selection is enabled first (before showing widget)
        let useRegionSelection: Bool
        do {
            let settingsData = try await APIClient.shared.get("/settings/models")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            struct ResponseWrapper: Codable {
                let status: String
                let settings: ModelSettingsPayload
            }
            struct ModelSettingsPayload: Codable {
                let useRegionSelection: Bool
            }
            let response = try decoder.decode(ResponseWrapper.self, from: settingsData)
            useRegionSelection = response.settings.useRegionSelection
        } catch {
            #if DEBUG
            DevLogger.shared.warning("[ASSISTANT_SESSION] Failed to load region selection setting, defaulting to false: \(error)", context: "HotkeyService")
            #endif
            useRegionSelection = false
        }
        
        // For region selection, do capture first (shows overlay), then show widget
        // For window capture, show widget first (existing behavior)
        let captureResult: WindowCaptureService.CaptureResult
        if useRegionSelection {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Using region selection capture (before showing widget)...", context: "HotkeyService")
            #endif
            captureResult = await ScreenRegionCaptureService.shared.captureSelectedRegion()
            
            guard captureResult.hasValidCapture, let imagePath = captureResult.imagePath else {
                #if DEBUG
                DevLogger.shared.error("[ASSISTANT_SESSION] Region capture failed: \(captureResult.displayError)", context: "HotkeyService")
                #endif
                return
            }
            
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Region capture successful: \(imagePath)", context: "HotkeyService")
            #endif
            
            // Now show the widget after capture completes
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Showing widget after region capture...", context: "HotkeyService")
            #endif
            AssistantSessionWindowController.show()
        } else {
            // Show the widget first for window capture (existing behavior)
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Showing widget...", context: "HotkeyService")
            #endif
            AssistantSessionWindowController.show()
            
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Using Swift WindowCaptureService for capture...", context: "HotkeyService")
            #endif
            captureResult = await WindowCaptureService.shared.captureActiveWindow()
            
            guard captureResult.hasValidCapture, let imagePath = captureResult.imagePath else {
                #if DEBUG
                DevLogger.shared.error("[ASSISTANT_SESSION] Window capture failed: \(captureResult.displayError)", context: "HotkeyService")
                #endif
                return
            }
            
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Window capture successful: \(imagePath)", context: "HotkeyService")
            #endif
        }
        
        // Get imagePath for both paths
        guard let imagePath = captureResult.imagePath else {
            return
        }
        
        // Start the AssistantSession flow with pre-detected selection
        // This prevents double-detection and clipboard interference
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] 📦 Passing pre-detected selection to ViewModel...", context: "HotkeyService")
        if selectionResult.hasSelection {
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Passing selection with \(selectionResult.selectedText.count) chars", context: "HotkeyService")
        } else {
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Passing empty selection result (full document mode)", context: "HotkeyService")
        }
        #endif

        // Seed the unified AssistantSession widget's input modality from the user's
        // `assistantSession.default_input_modality` preference *before*
        // kicking off the flow. The MainFlow orchestrator branches on
        // `viewModel.inputMode` after OCR to decide whether to start the
        // mic recording loop or to await a typed-input submission, so the
        // value must be in place before that branch executes. We do this
        // best-effort: a fetch failure leaves `inputMode` at its `.speak`
        // default, preserving the legacy behavior for that single
        // invocation. The widget header toggle remains usable either way.
        await applyDefaultInputModalityPreference()

        // Seed the typed-input "Detected Application" strip from the
        // AppleScript-derived `CaptureResult.appName` -- the same value the
        // legacy Enhanced Suggestion widget rendered as `viewModel.appName`.
        // `WindowCaptureService` (window mode) and `ScreenRegionCaptureService`
        // (region mode) both populate this field via the
        // `first process whose frontmost is true` AppleScript, so it is the
        // canonical source for "what app are we AssistantSession-ing against right
        // now" and is available whenever capture itself succeeded.
        // Set this *before* `startAssistantSessionFlow` so the strip has a value the
        // first frame the typed-input UI renders.
        if let viewModel = AssistantSessionWindowController.sharedController?.viewModel {
            viewModel.detectedApplicationName = captureResult.appName
            #if DEBUG
            DevLogger.shared.info(
                "[ASSISTANT_SESSION] Seeded detectedApplicationName = '\(captureResult.appName)' from CaptureResult",
                context: "HotkeyService"
            )
            #endif
        }

        await AssistantSessionWindowController.sharedController?.viewModel.startAssistantSessionFlow(
            activityImagePath: imagePath,
            preDetectedSelection: selectionResult
        )
        
        // Clean up the capture file after the flow starts
        do {
            if FileManager.default.fileExists(atPath: imagePath) {
                try FileManager.default.removeItem(atPath: imagePath)
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Cleaned up capture file: \(imagePath)", context: "HotkeyService")
                #endif
            }
        } catch {
            #if DEBUG
            DevLogger.shared.warning("[ASSISTANT_SESSION] Failed to clean up capture file: \(error)", context: "HotkeyService")
            #endif
        }
    }

    /// Read `assistantSession.default_input_modality` from server settings
    /// and seed the live widget's `viewModel.inputMode` accordingly. The
    /// settings GET (`/settings/assistant-session`) returns the full
    /// `AssistantSessionSettings` shape, including the required modality
    /// field added by the AssistantSession unification. Any failure here is
    /// non-fatal: we log and leave the view model at its `.speak`
    /// default so a missing or unreachable settings endpoint never
    /// blocks the user from getting a AssistantSession output.
    @MainActor
    private func applyDefaultInputModalityPreference() async {
        guard let viewModel = AssistantSessionWindowController.sharedController?.viewModel else {
            return
        }

        do {
            let data = try await self.apiClient.get("/settings/assistant-session")
            let decoder = JSONDecoder()
            // Wire-level field is `default_input_modality`; the DTO
            // already declares the matching `CodingKeys` so we don't need
            // a snake-case strategy here.
            struct ResponseWrapper: Decodable {
                let status: String
                let settings: AssistantSessionSettings
            }
            let response = try decoder.decode(ResponseWrapper.self, from: data)
            viewModel.inputMode = response.settings.resolvedDefaultInputMode

            // Direct assignment (rather than going through
            // `switchInputMode(to:)`) is intentional: the initial
            // seed runs before any audio capture or session exists,
            // and `switchInputMode`'s `.speak` branch would attempt
            // to re-arm recording with no `sessionId`. We do, however,
            // need to drive the window resize ourselves so the widget
            // opens at the correct dimensions on the very first show
            // when the preference is `.type`. Without this, the
            // window stays at the compact `300x138` floor and the
            // typed-input slot's full ES interior renders inside a
            // sub-pixel container until the user toggles modality
            // and back. The publish is a no-op on `.speak` (target
            // size matches the initial frame anyway), so this is
            // safe to call unconditionally.
            viewModel.publishWidgetSizeForCurrentModality()

            #if DEBUG
            DevLogger.shared.info(
                "[ASSISTANT_SESSION] Seeded inputMode = \(viewModel.inputMode) from default_input_modality preference",
                context: "HotkeyService"
            )
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.warning(
                "[ASSISTANT_SESSION] Failed to load default_input_modality preference, leaving inputMode at default (.speak): \(error)",
                context: "HotkeyService"
            )
            #endif
        }
    }

    // Start and await a voice transcription for the AssistantSession flow
    @MainActor
    func startVoiceTranscriptionForAssistantSession() async throws -> String {
#if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] startVoiceTranscriptionForAssistantSession called (waiting for transcription; recording will be started by view model on .modelReady)", context: "HotkeyService")
#endif
        let viewModel = AssistantSessionWindowController.sharedController?.viewModel
        return try await withTimeout(seconds: 30) {
            try await withCheckedThrowingContinuation { continuation in
                Task {
                    do {
                        try await viewModel?.audioCaptureService.startRecording(flowContext: "assistantSession")
                        // Wait for recording to finish and get the transcription (implement this logic as needed)
                        // For now, simulate transcription result
                        let transcription = "Simulated transcription result"
                        continuation.resume(returning: transcription)
                    } catch {
                        continuation.resume(throwing: error)
                    }
                }
            }
        }
    }
    
    // Add a timeout helper function
    private func withTimeout<T>(seconds: TimeInterval, operation: @escaping () async throws -> T) async throws -> T {
        try await withThrowingTaskGroup(of: T.self) { group in
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                throw NSError(domain: BasilTeamIdentity.assistantSession.displayName, code: 408, 
                             userInfo: [NSLocalizedDescriptionKey: "Transcription timeout"])
            }
            group.addTask {
                return try await operation()
            }
            let result = try await group.next()!
            group.cancelAll()
            return result
        }
    }
    
    @MainActor
    func handleAssistantSessionKeyRelease(pressDuration: TimeInterval) async {
        // Fetch AssistantSession settings to check if push-to-talk is enabled
        do {
            let data = try await self.apiClient.get("/settings")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            
            struct PreferencesResponse: Codable {
                let status: String
                let preferences: PreferencesData
            }
            
            struct PreferencesData: Codable {
                let assistantSession: AssistantSessionSettings
            }
            
            let response = try decoder.decode(PreferencesResponse.self, from: data)
            let settings = response.preferences.assistantSession
            
            guard settings.enablePushToTalk else {
                // Push-to-talk disabled, use normal behavior (wait for second press)
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Push-to-talk disabled, ignoring key release", context: "HotkeyService")
                #endif
                return
            }
            
            let thresholdSeconds = Double(settings.pushToTalkThresholdMs) / 1000.0
            
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Push-to-talk enabled: duration=\(String(format: "%.3f", pressDuration))s, threshold=\(String(format: "%.3f", thresholdSeconds))s", context: "HotkeyService")
            #endif
            
            if pressDuration >= thresholdSeconds {
                // Auto-process: stop recording if widget is recording
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Threshold exceeded, auto-stopping recording", context: "HotkeyService")
                #endif
                
                if let vm = AssistantSessionWindowController.sharedController?.viewModel, vm.isRecording {
                    vm.stopRecording()
                }
            } else {
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Below threshold, waiting for second press", context: "HotkeyService")
                #endif
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("[ASSISTANT_SESSION] Failed to fetch settings: \(error)", context: "HotkeyService")
            #endif
        }
    }
}

// Add these response models at the top or in a shared models file:
struct AssistantSessionStartResponse: Decodable {
    let session_id: String
    let ocr_text: String
}

struct AssistantOutputResponse: Decodable {
    let assistant_output: String
}
