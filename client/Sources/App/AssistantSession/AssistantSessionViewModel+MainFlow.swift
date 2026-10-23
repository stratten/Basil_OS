import SwiftUI
import Combine
import Foundation

// MARK: - Main Flow: Primary AssistantSession Workflow
extension AssistantSessionViewModel {
    
    // MARK: - AssistantSession Submission

    func submitAssistantSession() async {
        assistantSessionStatus = .running
        do {
            guard let _ = ocrText, !transcriptionText.isEmpty else {
                throw NSError(domain: BasilTeamIdentity.assistantSession.displayName, code: 400, userInfo: [NSLocalizedDescriptionKey: "Missing OCR or transcription text"])
            }
            // Instead of making another API request, just update the UI state
            // The actual API request is handled in HotkeyHandler_AssistantSession.swift
            assistantSessionStatus = .completed
            NotificationCenter.default.post(name: NSNotification.Name("AssistantOutputHistoryDidUpdate"), object: nil)
        } catch {
            errorMessage = error.localizedDescription
            assistantSessionStatus = .failed
        }
    }
    
    // MARK: - Recording Control
    
    func stopRecording() {
        // Stop the underlying audio capture and send data for transcription
        audioCaptureService.stopRecording(sendAudioData: true, flowContext: "assistantSession")

        // Speak-modality commit seam: from this point the user can no
        // longer flip back to typed input -- the recording is locked in
        // and about to be uploaded. Mirrors the agentTask widget where
        // `completeCapture()` is the last action before the capture
        // panel transitions away.
        if !isRefinementMode {
            inputCommitted = true
        }

        // If in refinement mode, trigger refinement processing
        if isRefinementMode {
            Task {
                await processRefinementAudio()
            }
        }
    }

    // MARK: - Modality Switching (mid-flow)

    /// Bidirectional Speak ↔ Type switch invoked by the header toggle.
    /// Mirrors `AgentTaskCaptureViewModel.enterTextEntryMode()` /
    /// `enterVoiceMode()` exactly: stop the audio engine on the way out
    /// of speak, re-arm it on the way back in.
    ///
    /// No-ops once the user has committed input (toggle is hidden in
    /// that case anyway, but we double-gate here to defend against
    /// races between the header binding and an in-flight commit).
    func switchInputMode(to newMode: AssistantSessionInputMode) async {
        guard !inputCommitted else {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] switchInputMode ignored: input already committed", context: "AssistantSessionViewModel")
            #endif
            return
        }
        guard newMode != inputMode else { return }

        switch newMode {
        case .type:
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Switching to .type modality (mid-flow); tearing down audio capture", context: "AssistantSessionViewModel")
            #endif
            // Mirror enterTextEntryMode(): stop the audio engine
            // unconditionally and discard any captured audio so a later
            // switch back to .speak starts fresh.
            audioCaptureService.stopRecording(sendAudioData: false, flowContext: "assistantSession")
            audioCaptureService.clearRecordingData()
            isRecording = false
            audioLevel = 0
            transcriptionText = ""
            recordingMonitorTask?.cancel()
            recordingMonitorTask = nil

            // Reset transcription status so the shared bubble-state
            // helpers stop reporting "processing" while we're sitting
            // in the typed editor with nothing actually streaming.
            // `startAssistantSessionFlow` sets `transcriptionStatus = .running`
            // up front to drive the speak-mode UI, but in typed mode
            // there's no recording in flight -- once OCR finishes
            // (or already has) the bubble should sit at idle (blue)
            // until the user submits, at which point `assistantSessionStatus`
            // takes over and flips the bubble to processing (green).
            if transcriptionStatus == .running {
                transcriptionStatus = .idle
            }

            inputMode = .type
            // Defensive reset: a stale typed buffer from an earlier
            // toggle round-trip would otherwise reappear. Matches
            // agentTask's `textPrompt = ""` on every modality entry.
            typedInstruction = ""
            typedInputSubmissionRequested = false

        case .speak:
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Switching to .speak modality (mid-flow); re-arming audio capture", context: "AssistantSessionViewModel")
            #endif
            inputMode = .speak
            typedInstruction = ""
            typedInputSubmissionRequested = false

            // Re-arm audio capture only if we already have a backend
            // session. Pre-OCR (no sessionId yet) the OCR-firstChunk
            // handler in `startAssistantSessionFlow` will do the initial
            // recording start when it sees `inputMode == .speak`.
            guard sessionId != nil else {
                // No session yet -- restore the .running marker so the
                // shared progress/bubble helpers reflect "we're going
                // to be recording shortly" while OCR is still in flight,
                // matching the speak-from-start flow.
                transcriptionStatus = .running
                publishWidgetSizeForCurrentModality()
                return
            }

            do {
                try await audioCaptureService.startRecording(flowContext: "assistantSession")
                // Only flip back to .running on a successful re-arm so
                // a failed start doesn't leave the bubble lying about
                // an active recording.
                transcriptionStatus = .running
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Re-armed audio capture after modality switch", context: "AssistantSessionViewModel")
                #endif
            } catch {
                if !isCanceled {
                    transcriptionStatus = .failed
                    errorMessage = "Failed to start recording: \(error.localizedDescription)"
                    #if DEBUG
                    DevLogger.shared.error("[ASSISTANT_SESSION] Re-arm startRecording failed: \(error)", context: "AssistantSessionViewModel")
                    #endif
                }
            }
        }

        // Drive the window resize through the existing
        // `idealSizeUpdateRequest` channel. The window controller's
        // `resizeWindow(to:)` anchors the top-right corner and animates
        // via `setFrame(_:display:animate:)`, which makes the widget
        // grow leftward (away from the screen edge it docks against) and
        // shrink back smoothly on the way out of typed mode.
        publishWidgetSizeForCurrentModality()
    }

    /// Emit the appropriate widget size for the current `inputMode` /
    /// `inputCommitted` state. Centralized so both the toggle and any
    /// initial-mode seeding (e.g. the default-modality preference at
    /// widget show time) flow through the same animated resize seam.
    @MainActor
    func publishWidgetSizeForCurrentModality() {
        let target = idealWindowSizeForCurrentModality()
        currentIdealWidgetWidth = target.width
        currentIdealWidgetHeight = target.height
        idealSizeUpdateRequest.send((width: target.width, height: target.height))
    }

    /// Heuristic-free size table keyed off modality + commit state.
    /// Typed-input slot uses the legacy ES footprint (550x420) so the
    /// recovered ES interior (expandable OCR + model picker + flex
    /// editor + bottom action row) has the room it was designed
    /// against. Everything else (speak, processing pre-result, post-
    /// commit) uses the historical compact dimensions.
    ///
    /// The speak-mode height is sized to match the compact React capture
    /// surface. The web renderer reports later content-driven adjustments
    /// through the same resize channel.
    private func idealWindowSizeForCurrentModality() -> (width: CGFloat, height: CGFloat) {
        if inputMode == .type && !inputCommitted {
            return (width: 550, height: 420)
        }
        return (width: 260, height: 120)
    }
    
    // MARK: - Operation Control
    
    func cancelOperation() {
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] cancelOperation called - canceling all pending operations", context: "AssistantSessionViewModel")
        #endif
        
        // Set cancellation flag to prevent further processing
        isCanceled = true
        
        // 1. Cancel all ongoing async tasks
        ocrStreamingTask?.cancel()
        audioUploadTask?.cancel()
        recordingMonitorTask?.cancel()
        
        // 2. Stop recording if in progress (without sending audio data)
        if isRecording {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Stopping recording without sending audio data", context: "AssistantSessionViewModel")
            #endif
            audioCaptureService.stopRecording(sendAudioData: false)
        }
        
        // 3. Cancel timer if running
        timerCancellable?.cancel()
        timerCancellable = nil
        
        // 4. Clean up backend session if one was created
        if let sessionId = sessionId {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Cleaning up backend session: \(sessionId)", context: "AssistantSessionViewModel")
            #endif
            Task { [sessionId] in
                await self.cleanupBackendSession(sessionId: sessionId)
            }
        }
        
        // 5. Reset all UI state to canceled/failed state
        ocrStatus = .failed
        transcriptionStatus = .failed
        assistantSessionStatus = .failed
        errorMessage = "Operation canceled by user"
        transcriptionText = ""
        assistantOutput = ""
        thinkingContent = nil
        ocrText = nil
        sessionId = nil
        
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] All cleanup operations completed", context: "AssistantSessionViewModel")
        #endif
        
        // 6. Close the window
        NotificationCenter.default.post(name: NSNotification.Name("CloseAssistantSessionWidgetRequest"), object: nil)
    }
    
    func minimizeWidget() {
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] User requested to minimize widget", context: "AssistantSessionViewModel")
        #endif
        onMinimize?()
    }
    
    // MARK: - Main AssistantSession Flow
    
    func startAssistantSessionFlow(activityImagePath: String, preDetectedSelection: TextSelectionResult? = nil) async {
        // Check if already canceled before starting
        guard !isCanceled else {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Flow start canceled - operation was already canceled", context: "AssistantSessionViewModel")
            #endif
            return
        }
        
        // Reset cancellation flag for new operation
        isCanceled = false
        
        // Reset statuses
        ocrStatus = .idle
        transcriptionStatus = .idle
        assistantSessionStatus = .idle
        errorMessage = nil
        combinedResult = ""
        assistantOutput = ""
        thinkingContent = nil
        transcriptionText = ""
        ocrText = nil
        sessionId = nil
        sampleSaved = false
        savingSample = false

        // Reset typed-input modality state. `inputMode` itself is NOT
        // reset here -- the hotkey handler sets it from the user's
        // `default_input_modality` preference before invoking this flow,
        // and the widget header toggle may have flipped it again at
        // present time. Both are valid sources of truth; clobbering them
        // here would race the UI.
        typedInstruction = ""
        typedInputSubmissionRequested = false
        inputCommitted = false

        // Use pre-detected selection if provided, otherwise detect now
        if let preDetected = preDetectedSelection {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Using pre-detected text selection (from hotkey handler)", context: "AssistantSessionViewModel")
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Pre-detected selection length: \(preDetected.selectedText.count) chars", context: "AssistantSessionViewModel")
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Pre-detected selection preview: '\(preDetected.selectedText.prefix(100))'...", context: "AssistantSessionViewModel")
            if preDetected.selectedText.count > 100 {
                DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Pre-detected selection ending: '...'\(preDetected.selectedText.suffix(100))'", context: "AssistantSessionViewModel")
            }
            #endif
            selectionContext = preDetected
            hasTextSelection = preDetected.hasSelection
        } else {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] No pre-detected selection - detecting now...", context: "AssistantSessionViewModel")
            #endif
            selectionContext = await textSelectionService.detectTextSelection()
            hasTextSelection = selectionContext?.hasSelection ?? false
            
            #if DEBUG
            if hasTextSelection {
                DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] On-demand detection found selection: \(selectionContext?.selectedText.count ?? 0) chars", context: "AssistantSessionViewModel")
            } else {
                DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] On-demand detection found no selection", context: "AssistantSessionViewModel")
            }
            #endif
        }
        
        if hasTextSelection {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] ✅ Text selection ACTIVE: '\(selectionContext?.selectedText.prefix(50) ?? "")'... (total length: \(selectionContext?.selectedText.count ?? 0) chars)", context: "AssistantSessionViewModel")
            #endif
        } else {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] ❌ No text selection - proceeding with full document mode", context: "AssistantSessionViewModel")
            #endif
        }

        // --- 1. Start backend session with Swift-captured image path ---
        ocrStatus = .running
        transcriptionStatus = .running
        
        // Create task for OCR streaming to allow cancellation
        ocrStreamingTask = Task { @MainActor in
            do {
                let apiBase = APIClient.shared.baseURL
                guard let url = URL(string: "\(apiBase)/assistant-sessions/start") else {
                    throw NSError(domain: BasilTeamIdentity.assistantSession.displayName, code: 400,
                                  userInfo: [NSLocalizedDescriptionKey: "Invalid backend OCR API URL"])
                }
                var request = URLRequest(url: url)
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                
                // Send the image path as a JSON object { "image_path": "..." }
                let requestBody = AssistantSessionStartRequest(image_path: activityImagePath)
                request.httpBody = try JSONEncoder().encode(requestBody)
                
                let (stream, response) = try await URLSession.shared.bytes(for: request)
                
                // Check for cancellation before processing response
                if Task.isCancelled || isCanceled {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] OCR streaming canceled before response processing", context: "AssistantSessionViewModel")
                    #endif
                    return
                }
                
                // Validate HTTP status code before streaming
                if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
                    throw NSError(
                        domain: BasilTeamIdentity.assistantSession.displayName,
                        code: httpResponse.statusCode,
                        userInfo: [NSLocalizedDescriptionKey: "Backend OCR API error: HTTP \(httpResponse.statusCode)"]
                    )
                }
                let decoder = JSONDecoder()
                var firstChunk = true
                for try await line in stream.lines {
                    // Check for cancellation in streaming loop
                    if Task.isCancelled || isCanceled {
                        #if DEBUG
                        DevLogger.shared.info("[ASSISTANT_SESSION] OCR streaming canceled during line processing", context: "AssistantSessionViewModel")
                        #endif
                        return
                    }
                    
                    let dataLine = Data(line.utf8)
                    let chunk = try decoder.decode(AssistantSessionStartChunk.self, from: dataLine)
                    if firstChunk {
                        firstChunk = false
                        sessionId = chunk.session_id

                        // Recording + recording monitor are speak-modality
                        // only. In `.type` mode the widget will collect a
                        // typed instruction (or none) and the post-OCR
                        // branch below uploads it directly. Skipping the
                        // recording start avoids spuriously holding the
                        // microphone and tripping the audio-capture
                        // failure path when the user never intended to
                        // speak.
                        if inputMode == .speak {
                            // Start recording as soon as we have the session
                            Task {
                                // Check for cancellation before starting recording
                                if Task.isCancelled || isCanceled {
                                    #if DEBUG
                                    DevLogger.shared.info("[ASSISTANT_SESSION] Recording start canceled", context: "AssistantSessionViewModel")
                                    #endif
                                    return
                                }

                                #if DEBUG
                                DevLogger.shared.info("[ASSISTANT_SESSION] Calling startRecording...", context: "AssistantSessionViewModel")
                                #endif
                                do {
                                    try await audioCaptureService.startRecording(flowContext: "assistantSession")
                                    #if DEBUG
                                    DevLogger.shared.info("[ASSISTANT_SESSION] startRecording completed successfully", context: "AssistantSessionViewModel")
                                    #endif
                                } catch {
                                    // Check for cancellation before setting error state
                                    if !Task.isCancelled && !isCanceled {
                                        transcriptionStatus = .failed
                                        errorMessage = "Failed to start recording: \(error.localizedDescription)"
                                        #if DEBUG
                                        DevLogger.shared.error("[ASSISTANT_SESSION] startRecording failed: \(error)", context: "AssistantSessionViewModel")
                                        #endif
                                    }
                                }
                            }

                            // The post-OCR await is now driven by
                            // `inputCommitted` (set from `stopRecording()`
                            // / typed Submit), so the legacy
                            // recording-state monitor is no longer needed
                            // to release the continuation. Modality
                            // toggling stops/restarts recording via
                            // `switchInputMode(to:)` independently.
                        } else {
                            #if DEBUG
                            DevLogger.shared.info("[ASSISTANT_SESSION] Type modality -- skipping recording start; awaiting typed-input submission", context: "AssistantSessionViewModel")
                            #endif
                        }
                    }
                    if let text = chunk.ocr_text {
                        ocrText = text
                        ocrStatus = .completed
                        break
                    }
                }
            } catch {
                // Check for cancellation before setting error state
                if !Task.isCancelled && !isCanceled {
                    ocrStatus = .failed
                    errorMessage = error.localizedDescription
                    assistantSessionStatus = .failed
                }
                return
            }
        }
        
        // Wait for OCR task to complete (or be canceled)
        await ocrStreamingTask?.value
        
        // Check if operation was canceled after OCR
        if isCanceled {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Operation canceled after OCR phase", context: "AssistantSessionViewModel")
            #endif
            return
        }

        // --- 2. Wait for the user-input phase to complete ---
        // We wait on a single commit signal (`inputCommitted`) rather
        // than on a modality-specific task. That way mid-flight Speak
        // ↔ Type toggles (driven by `switchInputMode`) don't prematurely
        // release this await -- only an explicit "Stop & Process" or
        // typed Submit does. The post-OCR upload branch below then
        // dispatches on whatever `inputMode` was at commit time.
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] OCR complete, awaiting input commit (modality at commit will pick upload path)", context: "AssistantSessionViewModel")
        #endif
        await awaitInputCommit()
        transcriptionStatus = .completed

        // Check if operation was canceled during the input phase
        if isCanceled {
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Operation canceled after input phase", context: "AssistantSessionViewModel")
            #endif
            return
        }

        guard let sessionId = sessionId else {
            if !isCanceled {
                assistantSessionStatus = .failed
                errorMessage = "No session ID available for this upload."
            }
            return
        }

        // --- 3. POST input to backend for AssistantSession ---
        assistantSessionStatus = .running

        if inputMode == .speak {
            guard let audioData = audioCaptureService.lastRecordingData, !audioData.isEmpty else {
                if !isCanceled {
                    assistantSessionStatus = .failed
                    errorMessage = "No audio was recorded."
                }
                return
            }
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] sessionId: \(sessionId) | audioData size: \(audioData.count) bytes", context: "AssistantSessionViewModel")
            #endif
            // `selectedModelId` is populated by the React reasoning-model
            // picker. When nil, the picker has not loaded a usable model and
            // the upload helper omits `model_id`, allowing the backend to use
            // its configured default. This is the same contract as the typed
            // branch immediately below.
            await uploadAudioAndStreamAssistantSession(
                sessionId: sessionId,
                audioData: audioData,
                modelId: selectedModelId
            )
        } else {
            // `.type`: trimmed-empty is normalized to nil inside the
            // upload helper, which omits both `audio_file` and
            // `instruction_text` to invoke the server's no-input
            // modality. So submit-empty is a deliberate user action
            // here, not an error condition.
            let instruction = typedInstruction.trimmingCharacters(in: .whitespacesAndNewlines)
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] sessionId: \(sessionId) | typed instruction length: \(instruction.count) chars (empty -> no-input modality)", context: "AssistantSessionViewModel")
            #endif
            await uploadInstructionTextAndStreamAssistantSession(
                sessionId: sessionId,
                instructionText: instruction.isEmpty ? nil : instruction,
                modelId: selectedModelId
            )
        }
    }

    // MARK: - Input Commit Latch

    /// Suspends until the user has committed input (either speak via
    /// `stopRecording()` or type via `submitTypedInstruction()`), the
    /// operation is canceled, or the session disappears.
    /// The latch is consumed (reset to `false`) on exit so a subsequent
    /// flow start within the same view model gets a fresh signal.
    private func awaitInputCommit() async {
        if inputCommitted {
            inputCommitted = false
            return
        }
        for await committed in $inputCommitted.values {
            if Task.isCancelled || isCanceled {
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Input-commit wait canceled", context: "AssistantSessionViewModel")
                #endif
                return
            }
            if committed {
                inputCommitted = false
                return
            }
        }
    }

    // MARK: - Setup-Launched Flow (Auto-Fire)

    /// Entry point for AssistantSession sessions launched by the setup
    /// assistant (the Dill onboarding demo).
    ///
    /// Unlike `startAssistantSessionFlow`, this path skips OCR entirely
    /// (the grounding context is the email body the setup agent pulled,
    /// not a screen capture) and skips the `awaitInputCommit` latch (the
    /// `instruction` was approved via the consent receipt the user just
    /// accepted, so there is nothing to ask the user about). It seeds the
    /// view-model state exactly as if a successful OCR run plus a typed
    /// Submit had already happened, hits the new
    /// `/assistant-sessions/start_from_text` endpoint to allocate a
    /// session id whose `ocr_result` is pre-seeded with `contextText`,
    /// then drives `uploadInstructionTextAndStreamAssistantSession`
    /// directly — the same code path the typed Submit button would have
    /// invoked, just without the manual click.
    ///
    /// `modelId`, when non-nil, is forwarded as the session's
    /// `selectedModelId` so the streaming upload pins the model the setup
    /// agent itself is running on; this mirrors the model inheritance
    /// `launch_agent_task` already enjoys from setup.
    @MainActor
    func startAssistantSessionFlowFromSetup(
        instruction: String,
        contextText: String,
        modelId: String?
    ) async {
        isCanceled = false

        // Seed view-model state to look exactly like a freshly OCR'd,
        // typed-submit-armed session. `ocrText` non-empty is the gate the
        // typed Submit button's `canSubmit` checks; setting it here means
        // even if the user does see the widget briefly before the auto-fire
        // kicks off, Submit is enabled rather than mysteriously grayed out.
        ocrText = contextText
        ocrStatus = .completed
        transcriptionStatus = .completed
        inputMode = .type
        typedInstruction = instruction
        typedInputSubmissionRequested = true
        inputCommitted = true
        selectedModelId = modelId
        errorMessage = nil
        combinedResult = ""
        assistantOutput = ""
        thinkingContent = nil

        // Allocate a backend session whose ocr_result slot is pre-seeded
        // with the provided context text. This is the no-OCR sibling of
        // /assistant-sessions/start; the streamed body mirrors that route
        // so we can reuse the existing AssistantSessionStartChunk decoder.
        let allocatedSessionId: String
        do {
            allocatedSessionId = try await startSessionFromText(contextText: contextText)
        } catch {
            #if DEBUG
            DevLogger.shared.error(
                "[ASSISTANT_SESSION] Failed to start setup-launched session from text: \(error.localizedDescription)",
                context: "AssistantSessionViewModel"
            )
            #endif
            assistantSessionStatus = .failed
            errorMessage = "Failed to start session: \(error.localizedDescription)"
            return
        }

        sessionId = allocatedSessionId
        assistantSessionStatus = .running

        // Fire the typed-instruction upload directly. This is the same
        // helper the typed-mode Submit button would call; we just bypass
        // the click by invoking it ourselves now that all preconditions
        // (session id, instruction text, model id) are in place.
        let trimmedInstruction = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        await uploadInstructionTextAndStreamAssistantSession(
            sessionId: allocatedSessionId,
            instructionText: trimmedInstruction.isEmpty ? nil : trimmedInstruction,
            modelId: modelId
        )
    }

    /// POSTs `{context_text: ...}` to the no-OCR session-start endpoint
    /// and returns the allocated session id. The endpoint's streamed body
    /// is shaped like `/start`'s (an initial `{session_id}` frame, then a
    /// `{session_id, ocr_text}` echo frame), so we reuse
    /// `AssistantSessionStartChunk` for decoding the first line.
    private func startSessionFromText(contextText: String) async throws -> String {
        struct AssistantSessionStartFromTextRequest: Codable {
            let context_text: String
        }

        let apiBase = APIClient.shared.baseURL
        guard let url = URL(string: "\(apiBase)/assistant-sessions/start_from_text") else {
            throw NSError(
                domain: BasilTeamIdentity.assistantSession.displayName,
                code: 400,
                userInfo: [NSLocalizedDescriptionKey: "Invalid /assistant-sessions/start_from_text URL"]
            )
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(
            AssistantSessionStartFromTextRequest(context_text: contextText)
        )

        let (stream, response) = try await URLSession.shared.bytes(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw NSError(
                domain: BasilTeamIdentity.assistantSession.displayName,
                code: http.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "start_from_text returned HTTP \(http.statusCode)"]
            )
        }

        let decoder = JSONDecoder()
        for try await line in stream.lines {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty { continue }
            guard let data = trimmed.data(using: .utf8) else { continue }
            let chunk = try decoder.decode(AssistantSessionStartChunk.self, from: data)
            if let err = chunk.error, !err.isEmpty {
                throw NSError(
                    domain: BasilTeamIdentity.assistantSession.displayName,
                    code: 500,
                    userInfo: [NSLocalizedDescriptionKey: err]
                )
            }
            // First frame carries the session id; we have everything we need
            // and the second (ocr_text echo) frame is a no-op for our purposes.
            return chunk.session_id
        }

        throw NSError(
            domain: BasilTeamIdentity.assistantSession.displayName,
            code: 500,
            userInfo: [NSLocalizedDescriptionKey: "start_from_text closed before returning a session id"]
        )
    }
}

