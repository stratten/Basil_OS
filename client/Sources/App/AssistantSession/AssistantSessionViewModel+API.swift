import SwiftUI
import Combine
import Foundation

// MARK: - API: Network Operations and Backend Communication
extension AssistantSessionViewModel {
    
    // MARK: - Backend Session Cleanup
    
    /// Cancels and cleans up a backend AssistantSession session.
    /// This is a best-effort operation that does not throw on failure.
    /// - Parameter sessionId: The session ID to clean up.
    func cleanupBackendSession(sessionId: String) async {
        do {
            let apiBase = APIClient.shared.baseURL
            guard let url = URL(string: "\(apiBase)/assistant-sessions/\(sessionId)") else {
                #if DEBUG
                DevLogger.shared.warning("[ASSISTANT_SESSION] Invalid URL for session cleanup", context: "AssistantSessionViewModel")
                #endif
                return
            }
            
            var request = URLRequest(url: url)
            request.httpMethod = "DELETE"
            request.timeoutInterval = 5.0 // Short timeout for cleanup
            
            let (_, response) = try await URLSession.shared.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse {
                if (200...299).contains(httpResponse.statusCode) {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Backend session cleaned up successfully", context: "AssistantSessionViewModel")
                    #endif
                } else {
                    #if DEBUG
                    DevLogger.shared.warning("[ASSISTANT_SESSION] Backend session cleanup returned status: \(httpResponse.statusCode)", context: "AssistantSessionViewModel")
                    #endif
                }
            }
        } catch {
            #if DEBUG
            DevLogger.shared.warning("[ASSISTANT_SESSION] Failed to cleanup backend session: \(error)", context: "AssistantSessionViewModel")
            #endif
            // Don't throw - cleanup is best effort
        }
    }
    
    // MARK: - Audio Upload and Streaming
    
    /// Uploads recorded audio to the backend and streams the AssistantSession response.
    /// Handles multipart form data construction including optional text selection context.
    /// - Parameters:
    ///   - sessionId: The AssistantSession session ID.
    ///   - audioData: The recorded audio data (WAV format).
    ///   - modelId: Optional reasoning model id to use for this generation.
    ///     When `nil` or empty the `model_id` form field is omitted and the
    ///     backend falls back to its configured default model. Mirrors the
    ///     identically-named parameter on
    ///     :func:`uploadInstructionTextAndStreamAssistantSession` so the speak and
    ///     typed paths share one wire-level contract.
    func uploadAudioAndStreamAssistantSession(sessionId: String, audioData: Data, modelId: String? = nil) async {
        audioUploadTask = Task { @MainActor in
            do {
                // Check for cancellation before starting upload
                if Task.isCancelled || isCancelled {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Audio upload cancelled before starting", context: "AssistantSessionViewModel")
                    #endif
                    return
                }
                
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] POSTing audio to /assistant-sessions/\(sessionId)/process-input", context: "AssistantSessionViewModel")
                #endif
                let apiBase = APIClient.shared.baseURL
                guard let url = URL(string: "\(apiBase)/assistant-sessions/\(sessionId)/process-input") else {
                    throw NSError(domain: BasilTeamIdentity.assistantSession.displayName, code: 400, userInfo: [NSLocalizedDescriptionKey: "Invalid backend AssistantSession API URL"])
                }
                var request = URLRequest(url: url)
                request.httpMethod = "POST"
                request.timeoutInterval = 600.0
                request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
                let boundary = "Boundary-\(UUID().uuidString)"
                request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
                var body = Data()
                
                // Add text selection data if available
                if let selection = selectionContext, selection.hasSelection {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] 📤 Preparing to send text selection to backend", context: "AssistantSessionViewModel")
                    DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] Selection data - length: \(selection.selectedText.count), app: \(selection.applicationName), confidence: \(selection.confidence)", context: "AssistantSessionViewModel")
                    #endif
                    
                    let selectionData = [
                        "has_selection": selection.hasSelection,
                        "selected_text": selection.selectedText,
                        "containing_text": selection.containingText,
                        "application_name": selection.applicationName,
                        "confidence": selection.confidence
                    ] as [String : Any]
                    
                    if let selectionJson = try? JSONSerialization.data(withJSONObject: selectionData) {
                        body.append("--\(boundary)\r\n".data(using: .utf8)!)
                        body.append("Content-Disposition: form-data; name=\"text_selection\"\r\n\r\n".data(using: .utf8)!)
                        body.append(selectionJson)
                        body.append("\r\n".data(using: .utf8)!)
                        
                        #if DEBUG
                        DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] ✅ Text selection successfully added to multipart request (\(selectionJson.count) bytes)", context: "AssistantSessionViewModel")
                        #endif
                    } else {
                        #if DEBUG
                        DevLogger.shared.warning("[ASSISTANT_SESSION] [SELECTION-FLOW] ❌ Failed to serialize selection data to JSON", context: "AssistantSessionViewModel")
                        #endif
                    }
                } else {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] [SELECTION-FLOW] No text selection to send to backend", context: "AssistantSessionViewModel")
                    #endif
                }

                // Optional reasoning model override. Omitted entirely when
                // `modelId` is nil/empty so the backend's no-model-selected
                // default applies (matches the typed-upload helper). The
                // server-side accepting endpoint is `route_assistantSession.py`'s
                // `model_id: Optional[str] = Form(None, ...)` form field,
                // which has been wired since the typed path was added; the
                // speak path simply hadn't been threading it through yet.
                if let modelId = modelId, !modelId.isEmpty {
                    body.append("--\(boundary)\r\n".data(using: .utf8)!)
                    body.append("Content-Disposition: form-data; name=\"model_id\"\r\n\r\n".data(using: .utf8)!)
                    body.append(modelId.data(using: .utf8) ?? Data())
                    body.append("\r\n".data(using: .utf8)!)
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Including model_id=\(modelId) in audio upload", context: "AssistantSessionViewModel")
                    #endif
                }

                let filename = "audio.wav"
                let mimetype = "audio/wav"
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
                body.append("Content-Type: \(mimetype)\r\n\r\n".data(using: .utf8)!)
                body.append(audioData)
                body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
                request.httpBody = body
                
                // Use streaming response to handle NDJSON chunks
                let (stream, response) = try await URLSession.shared.bytes(for: request)
                
                // Check for cancellation after upload completes
                if Task.isCancelled || isCancelled {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Audio upload cancelled after completion", context: "AssistantSessionViewModel")
                    #endif
                    return
                }
                
                if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
                    var errorMessage = "HTTP \(httpResponse.statusCode)"
                    do {
                        for try await line in stream.lines {
                            errorMessage = line
                            break
                        }
                    } catch {}
                    
                    TrialExhaustionManager.shared.handleServerError(statusCode: httpResponse.statusCode, message: errorMessage)
                    
                    // Parse and provide user-friendly error messages
                    let userFriendlyMessage = parseErrorMessage(errorMessage, statusCode: httpResponse.statusCode)
                    throw NSError(domain: BasilTeamIdentity.assistantSession.displayName, code: httpResponse.statusCode, userInfo: [NSLocalizedDescriptionKey: userFriendlyMessage])
                }
                
                // Process streaming NDJSON response
                try await processStreamingResponse(stream: stream)
                
            } catch {
                // Check for cancellation before setting error state
                if !Task.isCancelled && !isCancelled {
                    assistantSessionStatus = .failed
                    errorMessage = error.localizedDescription
                }
            }
        }
        
        // Wait for audio upload task to complete (or be cancelled)
        await audioUploadTask?.value
    }
    
    // MARK: - Typed / No-Input Upload

    /// Submits the typed-input or no-input modality of the unified AssistantSession
    /// pipeline. Mirrors :func:`uploadAudioAndStreamAssistantSession` exactly --
    /// same route, same multipart envelope, same NDJSON streaming response
    /// processing -- but swaps the `audio_file` part for an
    /// `instruction_text` form field, or omits both parts to invoke the
    /// server's no-input default prompt.
    ///
    /// - Parameters:
    ///   - sessionId: Backend session previously created via `/start`.
    ///   - instructionText: Trimmed typed instruction. Pass `nil` (or
    ///     empty after trimming, which is normalised to `nil`) to invoke
    ///     the no-input modality.
    func uploadInstructionTextAndStreamAssistantSession(
        sessionId: String,
        instructionText: String?,
        modelId: String? = nil
    ) async {
        let normalisedInstruction: String? = {
            guard let raw = instructionText?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !raw.isEmpty else { return nil }
            return raw
        }()

        audioUploadTask = Task { @MainActor in
            do {
                if Task.isCancelled || isCancelled {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Instruction-text upload cancelled before starting", context: "AssistantSessionViewModel")
                    #endif
                    return
                }

                #if DEBUG
                let modalityLabel = normalisedInstruction == nil ? "no-input" : "typed (\(normalisedInstruction!.count) chars)"
                DevLogger.shared.info("[ASSISTANT_SESSION] POSTing \(modalityLabel) to /assistant-sessions/\(sessionId)/process-input", context: "AssistantSessionViewModel")
                #endif

                let apiBase = APIClient.shared.baseURL
                guard let url = URL(string: "\(apiBase)/assistant-sessions/\(sessionId)/process-input") else {
                    throw NSError(domain: BasilTeamIdentity.assistantSession.displayName, code: 400, userInfo: [NSLocalizedDescriptionKey: "Invalid backend AssistantSession API URL"])
                }
                var request = URLRequest(url: url)
                request.httpMethod = "POST"
                request.timeoutInterval = 600.0
                request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
                let boundary = "Boundary-\(UUID().uuidString)"
                request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
                var body = Data()

                if let selection = selectionContext, selection.hasSelection {
                    let selectionData = [
                        "has_selection": selection.hasSelection,
                        "selected_text": selection.selectedText,
                        "containing_text": selection.containingText,
                        "application_name": selection.applicationName,
                        "confidence": selection.confidence
                    ] as [String : Any]

                    if let selectionJson = try? JSONSerialization.data(withJSONObject: selectionData) {
                        body.append("--\(boundary)\r\n".data(using: .utf8)!)
                        body.append("Content-Disposition: form-data; name=\"text_selection\"\r\n\r\n".data(using: .utf8)!)
                        body.append(selectionJson)
                        body.append("\r\n".data(using: .utf8)!)
                    }
                }

                if let instruction = normalisedInstruction {
                    body.append("--\(boundary)\r\n".data(using: .utf8)!)
                    body.append("Content-Disposition: form-data; name=\"instruction_text\"\r\n\r\n".data(using: .utf8)!)
                    body.append(instruction.data(using: .utf8) ?? Data())
                    body.append("\r\n".data(using: .utf8)!)
                }

                // Model picker payload. Omitted entirely when nil so the
                // backend falls back to its configured default reasoning
                // model (matches the no-model-selected path in ES).
                if let modelId = modelId, !modelId.isEmpty {
                    body.append("--\(boundary)\r\n".data(using: .utf8)!)
                    body.append("Content-Disposition: form-data; name=\"model_id\"\r\n\r\n".data(using: .utf8)!)
                    body.append(modelId.data(using: .utf8) ?? Data())
                    body.append("\r\n".data(using: .utf8)!)
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Including model_id=\(modelId) in typed upload", context: "AssistantSessionViewModel")
                    #endif
                }

                body.append("--\(boundary)--\r\n".data(using: .utf8)!)
                request.httpBody = body

                let (stream, response) = try await URLSession.shared.bytes(for: request)

                if Task.isCancelled || isCancelled {
                    #if DEBUG
                    DevLogger.shared.info("[ASSISTANT_SESSION] Instruction-text upload cancelled after completion", context: "AssistantSessionViewModel")
                    #endif
                    return
                }

                if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
                    var errorMessage = "HTTP \(httpResponse.statusCode)"
                    do {
                        for try await line in stream.lines {
                            errorMessage = line
                            break
                        }
                    } catch {}

                    TrialExhaustionManager.shared.handleServerError(statusCode: httpResponse.statusCode, message: errorMessage)
                    
                    let userFriendlyMessage = parseErrorMessage(errorMessage, statusCode: httpResponse.statusCode)
                    throw NSError(domain: BasilTeamIdentity.assistantSession.displayName, code: httpResponse.statusCode, userInfo: [NSLocalizedDescriptionKey: userFriendlyMessage])
                }

                try await processStreamingResponse(stream: stream)

            } catch {
                if !Task.isCancelled && !isCancelled {
                    assistantSessionStatus = .failed
                    errorMessage = error.localizedDescription
                }
            }
        }

        await audioUploadTask?.value
    }

    // MARK: - Streaming Response Processing
    
    /// Processes the NDJSON streaming response from the backend.
    /// Decodes transcription and AssistantSession tokens, delegating to the streaming state machine.
    /// - Parameter stream: The async byte stream from URLSession.
    func processStreamingResponse(stream: URLSession.AsyncBytes) async throws {
        let decoder = JSONDecoder()
        var finalTranscription: String = ""
        
        struct TranscriptionProgress: Decodable {
            let completed_chunks: Int?
            let total_chunks: Int?
            let strategy: String?
            let stage_progress: Double?
            let current_time_seconds: Double?
            let audio_duration_seconds: Double?
            let message: String?
            let eta_seconds: Double?
            let chunk_index: Int?
            let chunk_count: Int?
        }
        
        struct StreamingChunk: Decodable {
            let stage: String?
            let transcription: String?
            let assistant_output_token: String?
            let assistant_output_partial: String?
            let assistant_output: String?
            let complete: Bool?
            let progress: TranscriptionProgress?
            let estimated_duration: Double?
            let error: String?
        }
        
        // Initialize streaming state
        streamingState = StreamingState()
        
        var completedSuccessfully = false
        for try await line in stream.lines {
            // Check for cancellation in streaming loop
            if Task.isCancelled || isCancelled {
                #if DEBUG
                DevLogger.shared.info("[ASSISTANT_SESSION] Streaming response cancelled during processing", context: "AssistantSessionViewModel")
                #endif
                return
            }
            
            let dataLine = Data(line.utf8)
            do {
                let chunk = try decoder.decode(StreamingChunk.self, from: dataLine)
                
                // Handle transcription keepalive/progress chunks
                if let stage = chunk.stage, stage == "transcribing" {
                    transcriptionStatus = .running
                    if let progress = chunk.progress,
                       let completed = progress.completed_chunks,
                       let total = progress.total_chunks {
                        #if DEBUG
                        DevLogger.shared.info("[ASSISTANT_SESSION] Transcription progress: \(completed)/\(total) chunks", context: "AssistantSessionViewModel")
                        #endif
                    }
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
                    transcriptionStatus = .completed
                    transcriptionProgressMessage = nil
                    transcriptionProgressFraction = nil
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
                    // Just flush remaining buffer - don't process final AssistantSession output again
                    // as we've already accumulated content from streaming tokens
                    flushStreamingBuffer(isFinal: true)
                    assistantSessionStatus = .completed
                    completedSuccessfully = true
                    NotificationCenter.default.post(name: NSNotification.Name("AssistantOutputHistoryDidUpdate"), object: nil)
                    break
                }
            } catch {
                #if DEBUG
                DevLogger.shared.warning("[ASSISTANT_SESSION] Failed to decode streaming chunk: \(error)", context: "AssistantSessionViewModel")
                #endif
                // Continue processing other chunks
            }
        }
        
        // Ensure we have final values set
        if !finalTranscription.isEmpty {
            transcriptionText = finalTranscription
        }
        
        if assistantSessionStatus == .failed { return }
        guard completedSuccessfully else {
            assistantSessionStatus = .failed
            errorMessage = "AssistantSession response ended before completion."
            NotificationCenter.default.post(name: NSNotification.Name("AssistantOutputHistoryDidUpdate"), object: nil)
            return
        }

        // Handle auto-paste and auto-close
        await handleAutoActions(finalAssistantOutput: "")
    }

    // MARK: - Auto Actions

    /// Handles automatic actions after AssistantSession completion based on user settings.
    /// Includes auto-paste (with markdown detection) and auto-close functionality.
    /// - Parameter finalAssistantOutput: The final AssistantSession output text (unused, kept for API compatibility).
    func handleAutoActions(finalAssistantOutput: String) async {
        Task { @MainActor in
            do {
                let settingsData = try await APIClient.shared.get("/settings/models")
                let settingsDecoder = JSONDecoder()
                settingsDecoder.keyDecodingStrategy = .convertFromSnakeCase
                struct ResponseWrapper: Codable { let status: String; let settings: ReasoningSettingsModel }
                let responseWrapper = try settingsDecoder.decode(ResponseWrapper.self, from: settingsData)

                self.shouldPersistUI = !responseWrapper.settings.closeAssistantSessionOnInsert

                // Auto-paste AssistantSession output if enabled - use assistantOutput (with thinking already extracted)
                if responseWrapper.settings.autoPasteAssistantOutput && !self.assistantOutput.isEmpty {
                    #if DEBUG
                    DevLogger.shared.info("Auto-paste enabled, pasting AssistantSession output (thinking excluded) with formatting", context: "AssistantSessionViewModel")
                    #endif

                    if MarkdownUtils.containsMarkdown(self.assistantOutput) {
                        self.pasteRichAssistantSession(self.assistantOutput)
                    } else {
                        self.pasteAssistantSession(self.assistantOutput)
                    }
                }

                // Auto-close widget if enabled
                if responseWrapper.settings.closeAssistantSessionOnInsert {
                    #if DEBUG
                    DevLogger.shared.info("Auto-close-on-insert enabled, sending close request", context: "AssistantSessionViewModel")
                    #endif
                    NotificationCenter.default.post(name: NSNotification.Name("CloseAssistantSessionWidgetRequest"), object: nil)
                } else {
                    #if DEBUG
                    DevLogger.shared.info("Auto-close-on-insert disabled, widget will persist with potentially adjusted UI.", context: "AssistantSessionViewModel")
                    #endif
                }
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to fetch model settings for auto-paste/auto-close: \(error)", context: "AssistantSessionViewModel")
                #endif
                self.shouldPersistUI = false
            }
        }
    }
    
    // MARK: - Error Message Parsing
    
    /// Parses raw error messages (including JSON) and returns user-friendly text.
    /// Handles authentication errors, payment errors, and other common failure cases.
    /// - Parameters:
    ///   - rawError: The raw error message from the server (may be JSON).
    ///   - statusCode: The HTTP status code.
    /// - Returns: A user-friendly error message.
    private func parseErrorMessage(_ rawError: String, statusCode: Int) -> String {
        // Try to parse as JSON first
        if let jsonData = rawError.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
           let errorMessage = json["error"] as? String {
            
            // Provide context based on the error type
            switch errorMessage.lowercased() {
            case let msg where msg.contains("trial") || msg.contains("included") || msg.contains("credit exhausted"):
                return "Your included Basil Cloud credit is used up. Sign in to continue with Basil Cloud, or switch to your own provider account."
            case let msg where msg.contains("invalid") && msg.contains("token"):
                return "Authentication failed. Please log out and log back in."
            case let msg where msg.contains("expired") && msg.contains("token"):
                return "Your session has expired. Please log out and log back in."
            case let msg where msg.contains("threshold"):
                return "Your Basil Cloud usage threshold was reached. Please review your billing settings to continue."
            case let msg where msg.contains("payment"):
                return "Basil Cloud needs a payment method before it can continue. Please add one in settings."
            case let msg where msg.contains("subscription"):
                return "Subscription inactive. Please check your subscription status."
            default:
                return errorMessage
            }
        }
        
        // Handle status code-specific messages
        switch statusCode {
        case 401:
            return "Authentication failed. Please log out and log back in."
        case 402:
            let lowercasedError = rawError.lowercased()
            if lowercasedError.contains("trial") || lowercasedError.contains("included") || lowercasedError.contains("credit exhausted") {
                return "Your included Basil Cloud credit is used up. Sign in to continue with Basil Cloud, or switch to your own provider account."
            }
            if lowercasedError.contains("threshold") {
                return "Your Basil Cloud usage threshold was reached. Please review your billing settings to continue."
            }
            return "Basil Cloud needs a payment method before it can continue. Please add one in settings."
        case 403:
            return "Access forbidden. Your subscription may be inactive."
        case 404:
            return "Service not found. Please try again."
        case 500...599:
            return "Server error. Please try again in a moment."
        default:
            return "Request failed with status \(statusCode). Please try again."
        }
    }
}
