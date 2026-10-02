import SwiftUI
import Combine
import Foundation

// MARK: - Refinement: Iterative Refinement Mode
extension AssistantSessionViewModel {
    
    // MARK: - Refinement Mode Control
    
    func enterRefinementMode() {
        guard assistantSessionStatus == .completed else {
            #if DEBUG
            DevLogger.shared.warning("[ASSISTANT_SESSION] Cannot enter refinement mode - AssistantSession not completed", context: "AssistantSessionViewModel")
            #endif
            return
        }

        isRefinementMode = true
        showRefinementIndicator = true

        // Store initial request if not already stored
        if initialRequest.isEmpty {
            initialRequest = transcriptionText
        }

        // Reset for new refinement
        transcriptionStatus = .idle
        assistantSessionStatus = .idle
        errorMessage = nil
        
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] Entered refinement mode for session: \(sessionId ?? "unknown")", context: "AssistantSessionViewModel")
        #endif
    }
    
    // MARK: - Refinement Recording
    
    func startRefinementRecording() async {
        guard isRefinementMode else {
            #if DEBUG
            DevLogger.shared.warning("[ASSISTANT_SESSION] Cannot start refinement recording - not in refinement mode", context: "AssistantSessionViewModel")
            #endif
            return
        }
        
        // No new OCR needed - use existing screen context
        transcriptionStatus = .running
        
        do {
            // Start audio recording
            try await audioCaptureService.startRecording()
            isRecording = true
            
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Started refinement recording", context: "AssistantSessionViewModel")
            #endif
        } catch {
            // A switch to typed refinement during startup cancels the start and resets the status; that isn't a failure.
            guard transcriptionStatus == .running else { return }
            handleError("Failed to start refinement recording: \(error.localizedDescription)")
        }
    }

    /// Discards an in-progress (or still-starting) refinement recording without uploading it, so the typed refinement editor can take over.
    func discardRefinementRecordingForTypedInput() {
        guard isRefinementMode, isRecording || transcriptionStatus == .running else { return }
        transcriptionStatus = .idle
        audioCaptureService.stopRecording(sendAudioData: false, flowContext: "assistantSession")
        audioCaptureService.clearRecordingData()
        isRecording = false
        audioLevel = 0
    }
    
    // MARK: - Refinement Audio Processing
    
    func processRefinementAudio() async {
        guard sessionId != nil,
              audioCaptureService.lastRecordingData != nil else {
            handleError("No audio data available for refinement")
            return
        }
        
        transcriptionStatus = .completed
        assistantSessionStatus = .running

        await processRefinementStreamDirectly(instructionText: nil)
    }

    // MARK: - Refinement Text Processing

    /// Typed-instruction analog of :func:`processRefinementAudio`. The
    /// unified backend route accepts `instruction_text` in lieu of an
    /// `audio_file` part and skips transcription entirely. Refinement
    /// has no no-input modality (server-side rejects: there is nothing to
    /// refine toward without an instruction), so an empty trimmed value
    /// is short-circuited as a user-visible error here rather than hitting
    /// the network and bouncing.
    func processRefinementText(_ instructionText: String) async {
        let trimmed = instructionText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            handleError("Refinement requires a non-empty instruction")
            return
        }
        guard sessionId != nil else {
            handleError("No session available for refinement")
            return
        }

        transcriptionStatus = .completed
        assistantSessionStatus = .running

        await processRefinementStreamDirectly(instructionText: trimmed)
    }
    
    // MARK: - Refinement Streaming
    
    private func processRefinementStreamDirectly(instructionText: String?) async {
        // Choose the input modality: typed instruction takes precedence
        // when provided; otherwise we fall back to the audio buffer the
        // recording flow accumulated. Refinement requires *some* input,
        // so failing both branches is a hard error.
        guard let sessionId = sessionId else {
            handleError("No session ID available for refinement streaming")
            return
        }
        let audioData = audioCaptureService.lastRecordingData
        if instructionText == nil && (audioData == nil || audioData?.isEmpty == true) {
            handleError("No instruction or audio data available for refinement streaming")
            return
        }

        do {
            // Create the streaming request
            let url = URL(string: "\(APIClient.shared.baseURL)/assistant-sessions/\(sessionId)/refine")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
            
            // Create multipart form data
            let boundary = UUID().uuidString
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            
            var formData = Data()
            if let instruction = instructionText {
                formData.append("--\(boundary)\r\n".data(using: .utf8)!)
                formData.append("Content-Disposition: form-data; name=\"instruction_text\"\r\n\r\n".data(using: .utf8)!)
                formData.append(instruction.data(using: .utf8) ?? Data())
                formData.append("\r\n".data(using: .utf8)!)
            } else if let audioData = audioData {
                formData.append("--\(boundary)\r\n".data(using: .utf8)!)
                formData.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"refinement_audio.wav\"\r\n".data(using: .utf8)!)
                formData.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
                formData.append(audioData)
                formData.append("\r\n".data(using: .utf8)!)
            }
            if let selectedModelId, !selectedModelId.isEmpty {
                formData.append("--\(boundary)\r\n".data(using: .utf8)!)
                formData.append("Content-Disposition: form-data; name=\"model_id\"\r\n\r\n".data(using: .utf8)!)
                formData.append(selectedModelId.data(using: .utf8) ?? Data())
                formData.append("\r\n".data(using: .utf8)!)
            }
            formData.append("--\(boundary)--\r\n".data(using: .utf8)!)
            request.httpBody = formData
            
            let (asyncBytes, _) = try await URLSession.shared.bytes(for: request)
            
            var finalTranscription = ""
            
            // Initialize streaming state
            streamingState = StreamingState()
            pasteDecision = nil
            pasteOutcome = nil
            
            // Process streaming response
            var completedSuccessfully = false
            for try await line in asyncBytes.lines {
                // Check for cancellation
                guard !isCanceled else {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Refinement streaming canceled", context: "AssistantSessionViewModel")
                    #endif
                    return
                }
                
                guard !line.isEmpty else { continue }
                
                do {
                    // Define response structure for refinement streaming chunks
                    struct RefinementTranscriptionProgress: Decodable {
                        let strategy: String?
                        let stage_progress: Double?
                        let current_time_seconds: Double?
                        let audio_duration_seconds: Double?
                        let message: String?
                        let eta_seconds: Double?
                        let chunk_index: Int?
                        let chunk_count: Int?
                    }

                    struct RefinementStreamingChunk: Decodable {
                        let transcription: String?
                        let assistant_output_token: String?
                        let assistant_output_partial: String?
                        let assistant_output: String?
                        let complete: Bool?
                        let iteration_count: Int?
                        let stage: String?
                        let progress: RefinementTranscriptionProgress?
                        let error: String?
                        let paste_decision: String?
                    }
                    
                    let data = line.data(using: .utf8) ?? Data()
                    let chunk = try JSONDecoder().decode(RefinementStreamingChunk.self, from: data)

                    if let stage = chunk.stage, stage == "transcribing" {
                        transcriptionStatus = .running
                        if let progress = chunk.progress {
                            transcriptionProgressMessage = progress.message
                            transcriptionProgressFraction = progress.stage_progress
                        }
                        continue
                    }
                    
                    // Update transcription if provided
                    if let transcription = chunk.transcription {
                        finalTranscription = transcription
                        transcriptionText = transcription
                        currentRequest = transcription
                        transcriptionStatus = .completed
                        transcriptionProgressMessage = nil
                        transcriptionProgressFraction = nil
                    }
                    
                    // Update iteration count if provided
                    if let iteration = chunk.iteration_count {
                        iterationCount = iteration
                    }
                    
                    // Process streaming tokens with state machine
                    if let token = chunk.assistant_output_token {
                        processStreamingToken(token, isFinal: false)
                    }

                    // Check for completion
                    if chunk.complete == true {
                        if let serverError = chunk.error, !serverError.isEmpty {
                            flushStreamingBuffer(isFinal: true)
                            assistantSessionStatus = .failed
                            errorMessage = serverError
                            NotificationCenter.default.post(name: NSNotification.Name("AssistantOutputHistoryDidUpdate"), object: nil)
                            break
                        }
                        pasteDecision = chunk.paste_decision
                        flushStreamingBuffer(isFinal: true)
                        assistantSessionStatus = .completed
                        completedSuccessfully = true
                        NotificationCenter.default.post(name: NSNotification.Name("AssistantOutputHistoryDidUpdate"), object: nil)
                        break
                    }
                } catch {
                    #if DEBUG
                    DevLogger.shared.warning("[ASSISTANT_SESSION] Failed to decode refinement streaming chunk: \(error)", context: "AssistantSessionViewModel")
                    #endif
                    // Continue processing other chunks
                }
            }
            
            // Ensure we have final values set
            if !finalTranscription.isEmpty {
                transcriptionText = finalTranscription
                currentRequest = finalTranscription
            }
            
            if assistantSessionStatus == .failed { return }
            guard completedSuccessfully else {
                assistantSessionStatus = .failed
                errorMessage = "AssistantSession refinement ended before completion."
                NotificationCenter.default.post(name: NSNotification.Name("AssistantOutputHistoryDidUpdate"), object: nil)
                return
            }

            // Handle auto-paste for refinement (same as main AssistantSession flow)
            Task { @MainActor in
                do {
                    let settingsData = try await APIClient.shared.get("/settings/models")
                    let settingsDecoder = JSONDecoder()
                    settingsDecoder.keyDecodingStrategy = .convertFromSnakeCase
                    struct ResponseWrapper: Codable { let status: String; let settings: ReasoningSettingsModel }
                    let responseWrapper = try settingsDecoder.decode(ResponseWrapper.self, from: settingsData)

                    await self.performCompletionPaste(mode: responseWrapper.settings.assistantOutputPasteMode)
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed to fetch model settings for refinement auto-paste: \(error)", context: "AssistantSessionViewModel")
                    #endif
                }
            }
            
            #if DEBUG
            DevLogger.shared.info("[ASSISTANT_SESSION] Refinement \(iterationCount) completed successfully", context: "AssistantSessionViewModel")
            #endif
            
        } catch {
            handleError("Failed to process refinement stream: \(error.localizedDescription)")
        }
    }
    
    // MARK: - Error Handling
    
    func handleError(_ message: String) {
        errorMessage = message
        transcriptionStatus = .failed
        assistantSessionStatus = .failed
        
        #if DEBUG
        DevLogger.shared.error("[ASSISTANT_SESSION] Error: \(message)", context: "AssistantSessionViewModel")
        #endif
    }
}

