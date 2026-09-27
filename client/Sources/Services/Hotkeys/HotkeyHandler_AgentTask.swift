import Foundation
import AppKit
import Combine

extension HotkeyService {
    // MARK: - AgentTask Audio Capture Service
    
    /// AgentTask hotkey gate logic. Four mutually-exclusive cases, evaluated
    /// in order; the first match wins and returns immediately.
    ///
    /// 1. **Capture-widget recording active** → complete it. The capture
    ///    widget is the ephemeral panel used for new AgentTasks. A second
    ///    hotkey press while it's recording finishes the take and hands
    ///    the audio to the backend, which streams progress into the
    ///    result widget.
    /// 2. **Result-widget follow-up recording active** → complete it.
    ///    The result widget singleton owns its own inline follow-up
    ///    audio capture (see `AgentTaskResultWidgetController.followUpCaptureVM`).
    ///    A second hotkey press while a follow-up is recording finishes
    ///    that follow-up.
    /// 3. **Result widget visible AND focused row supports follow-up
    ///    AND row not currently processing** → start an inline follow-up
    ///    capture against the focused row's `agentTaskId`. Routes through
    ///    the singleton's public `startFollowUpCapture(rootTaskId:)`
    ///    entry point — same machinery as a click on the React sidebar's
    ///    follow-up affordance, never spawns a capture widget.
    /// 4. **Default** → spawn a fresh capture widget for a new agent task
    ///    via `StatusBarWindowCoordinator.showAgentTaskCaptureWidget()` (by
    ///    way of the existing `startAgentTaskCapture()` HTTP wake-word
    ///    callback). On capture completion, the widget hands off to the
    ///    result widget singleton, which folds the new agent into the
    ///    one-and-only history view.
    ///
    /// Note: gate 3 conservatively requires `agentTaskId != nil`. The JS
    /// bridge (`bridge.ts`) pushes `agentTaskId` and `supportsFollowUp` on
    /// every `agentStatusChanged` event, and follow-up eligibility now updates
    /// live when a focused task completes in place (see
    /// `useAgentStatusReporting.ts`), so the focused-row cache reflects the
    /// current terminal state without requiring the user to re-select the row.
    /// If no follow-up-eligible focus is present, gate 3 still falls through to
    /// gate 4 (new capture).
    @MainActor
    func handleAgentTaskHotkey() async {
        recordHotkeyPress(hotkeyId: "agentTask")

        #if DEBUG
        DevLogger.shared.info("[AGENT_TASK] AgentTask hotkey triggered", context: "HotkeyService")
        #endif

        // GATE 1: Capture-widget capture in flight → complete.
        if let captureVM = activeCaptureViewModel(), captureVM.isCapturing {
            #if DEBUG
            DevLogger.shared.info(
                "[AGENT_TASK] ⏹️ Capture-widget recording — completing capture",
                context: "HotkeyService"
            )
            #endif
            captureVM.completeCapture()
            return
        }

        // GATE 2: Result-widget inline follow-up capture in flight → complete.
        if AgentTaskFollowUpCaptureLease.shared.completeActiveCapture() {
            #if DEBUG
            DevLogger.shared.info(
                "[AGENT_TASK] ⏹️ Result-widget follow-up recording — completing follow-up",
                context: "HotkeyService"
            )
            #endif
            return
        }

        let blockingAudioOwners = AudioCaptureService.blockingRecordingOwners()
        if !blockingAudioOwners.isEmpty {
            DevLogger.shared.info(
                "[AGENT_TASK] Voice capture blocked by active microphone owner(s): \(blockingAudioOwners.joined(separator: ", "))",
                context: "HotkeyService"
            )
            return
        }

        // GATE 3: Result widget visible + focused row supports a follow-up
        //         and isn't currently processing → start inline follow-up.
        if AgentTaskFollowUpFocusRegistry.shared.startFocusedFollowUp() {
            return
        }

        // GATE 4: Default — spawn a fresh capture widget for a new agent task.
        #if DEBUG
        if let singleton = AgentTaskResultWidgetController.shared, singleton.isVisible {
            let focused = singleton.focusedRowState
            DevLogger.shared.info(
                "[AGENT_TASK] Result widget visible but no follow-up-eligible focus (agentTaskId=\(focused?.agentTaskId ?? "nil"), supportsFollowUp=\(focused?.supportsFollowUp ?? false), isProcessing=\(focused?.isProcessing ?? false)) — starting new capture",
                context: "HotkeyService"
            )
        } else {
            DevLogger.shared.info(
                "[AGENT_TASK] No result widget visible — starting new agentTask capture via hotkey",
                context: "HotkeyService"
            )
        }
        #endif
        await startAgentTaskCapture()
    }
    
    @MainActor
    private func isAgentTaskCaptureActive() async -> Bool {
        // Deprecated for hotkey flow: backend no longer owns capture lifecycle here.
        return false
    }
    
    /// Start a new agentTask capture session.
    /// This is the core capture initiation - can be called directly to bypass follow-up logic.
    @MainActor
    func startAgentTaskCapture() async {
        do {
            // Immediately notify backend to trigger UI; recording will be handled by the capture widget
            let requestBody: [String: Any] = [
                "wake_phrase": "hotkey_initiated", 
                "hotkey_mode": true
            ]
            
            let jsonData = try JSONSerialization.data(withJSONObject: requestBody)
            let _ = try await apiClient.post("/api/v1/voice-listener/wake-word-callback", body: jsonData)
            
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] ✅ Hotkey triggered UI immediately; recording handled by capture widget", context: "HotkeyService")
            #endif
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("[AGENT_TASK] ❌ Failed to start agentTask capture: \(error)", context: "HotkeyService")
            #endif
            
            // Clean up on failure (no local audio service started)
            HotkeyService.agentTaskAudioService = nil
        }
    }
    
        @MainActor
    private func stopAgentTaskCapture() async {
        #if DEBUG
        DevLogger.shared.info("[AGENT_TASK] 🛑 Stopping agentTask capture (using EXACT AssistantSession pattern)...", context: "HotkeyService")
        #endif
        
        // When a capture widget is active, delegate STOP+PROCESS to that widget's ViewModel.
        if let captureVM = activeCaptureViewModel(), captureVM.isCapturing {
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] ⏹️ Delegating stop to capture widget VM", context: "HotkeyService")
            #endif
            captureVM.completeCapture()
            return
        }
        
        // Fallback: if no capture widget is active, nothing to stop.
        #if DEBUG
        DevLogger.shared.warning("[AGENT_TASK] ⚠️ No active capture widget found to stop", context: "HotkeyService")
        #endif
    }
    
    @MainActor
    private func stopBackendCapture() async {
        // No-op for hotkey flow; backend does cleanup on process_audio receipt.
        return
    }
    
    @MainActor
    private func stopSwiftAudioCapture() async {
        guard let audioService = HotkeyService.agentTaskAudioService else { return }
        
        audioService.stopRecording(sendAudioData: false)
        agentTaskCancellables.removeAll()
        
        #if DEBUG
        DevLogger.shared.info("[AGENT_TASK] 🧹 Swift audio capture cleaned up", context: "HotkeyService")
        #endif
    }
    
    @MainActor
    private func processFinalAgentTaskAudio(audioData: Data) async {
        do {
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] 📤 Sending final audio to agentTask processing endpoint", context: "HotkeyService")
            #endif
            
            // Create new agentTask processing endpoint (mirroring AssistantSession pattern)
            let apiBase = apiClient.baseURL
            guard let url = URL(string: "\(apiBase)/api/v1/agent-tasks/process-audio") else {
                throw NSError(domain: BasilTeamIdentity.agentTask.displayName, code: 400,
                              userInfo: [NSLocalizedDescriptionKey: "Invalid agentTask processing API URL"])
            }
            
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.timeoutInterval = 30.0
            
            // Use multipart form data (same as AssistantSessions)
            let boundary = "Boundary-\(UUID().uuidString)"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            
            var body = Data()
            let filename = "agentTask.wav"
            let mimetype = "audio/wav"
            
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: \(mimetype)\r\n\r\n".data(using: .utf8)!)
            body.append(audioData)
            body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
            
            request.httpBody = body
            
            let (data, response) = try await URLSession.shared.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
                throw NSError(domain: BasilTeamIdentity.agentTask.displayName, code: httpResponse.statusCode,
                              userInfo: [NSLocalizedDescriptionKey: "AgentTask processing API error: HTTP \(httpResponse.statusCode)"])
            }
            
            // Process response
            if let responseJson = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] ✅ AgentTask processing response: \(responseJson)", context: "HotkeyService")
                #endif
                
                // Handle successful agentTask processing
                // The backend will trigger further processing through existing WebSocket events
            }
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("[AGENT_TASK] ❌ Failed to process final agentTask audio: \(error)", context: "HotkeyService")
            #endif
        }
        
        // Clean up audio data after processing to prevent memory leaks
        if let audioService = HotkeyService.agentTaskAudioService {
            // Force clear the audio data now that it's been processed
            audioService.clearRecordingData()
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] 🧹 Cleared agentTask audio data after processing", context: "HotkeyService")
            #endif
        }
    }

    // MARK: - Helpers
    @MainActor
    func activeCaptureViewModel() -> AgentTaskCaptureViewModel? {
        if let appDelegate = NSApplication.shared.delegate as? AppDelegate,
           let coordinator = appDelegate.statusBarManager?.windowCoordinator,
           let controller = coordinator.agentTaskCaptureController {
            return controller.anyCaptureViewModel
        }
        return nil
    }
    
    @MainActor
    func handleAgentTaskKeyRelease(pressDuration: TimeInterval) async {
        // Fetch agentTask settings to check if push-to-talk is enabled
        do {
            let data = try await apiClient.get("/settings")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            
            struct PreferencesResponse: Codable {
                let status: String
                let preferences: PreferencesData
            }
            
            struct PreferencesData: Codable {
                let agentTask: AgentTaskSettings
            }
            
            let response = try decoder.decode(PreferencesResponse.self, from: data)
            let settings = response.preferences.agentTask
            
            guard settings.enablePushToTalk else {
                // Push-to-talk disabled, use normal behavior (wait for second press)
                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] Push-to-talk disabled, ignoring key release", context: "HotkeyService")
                #endif
                return
            }
            
            let thresholdSeconds = Double(settings.pushToTalkThresholdMs) / 1000.0
            
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] Push-to-talk enabled: duration=\(String(format: "%.3f", pressDuration))s, threshold=\(String(format: "%.3f", thresholdSeconds))s", context: "HotkeyService")
            #endif
            
            if pressDuration >= thresholdSeconds {
                // Auto-process: complete capture if recording
                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] Threshold exceeded, auto-completing capture", context: "HotkeyService")
                #endif
                
                if let captureVM = activeCaptureViewModel(), captureVM.isCapturing {
                    captureVM.completeCapture()
                }
            } else {
                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] Below threshold, waiting for second press", context: "HotkeyService")
                #endif
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("[AGENT_TASK] Failed to fetch settings: \(error)", context: "HotkeyService")
            #endif
        }
    }
} 