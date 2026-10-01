import Foundation

// MARK: - Analysis Extension

extension LiveTranscriptionViewModel {
    
    // MARK: - Model Loading
    
    /// Load available reasoning models for analysis through the shared backend model-response contract.
    func loadAnalysisModels() async {
        isLoadingAnalysisModels = true
        do {
            // Load model settings
            let modelSettingsData = try await APIClient.shared.get("/settings/models")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            
            struct ResponseWrapper: Codable {
                let status: String
                let settings: ReasoningSettingsModelVM
            }
            let modelSettings = try decoder.decode(ResponseWrapper.self, from: modelSettingsData).settings
            
            #if DEBUG
            DevLogger.shared.info("Loading analysis models - API models enabled: \(modelSettings.useApiModels)", context: "LiveTranscriptionViewModel")
            #endif
            
            // Load installed local models
            let localModelsData = try await APIClient.shared.get("/models/installed")
            struct ModelVariant: Codable {
                let modelId: String  // Canonical registry ID from backend
                let name: String
                let capabilities: [String]?
                let valid: Bool?
            }
            struct ModelType: Codable {
                let variants: [String: ModelVariant]
            }
            let localModelsResponse = try decoder.decode([String: ModelType].self, from: localModelsData)
            
            #if DEBUG
            DevLogger.shared.info("Found \(localModelsResponse.count) local model types", context: "LiveTranscriptionViewModel")
            #endif
            
            var localModelsList: [ReasoningModelInfoVM] = []
            for (modelType, modelTypeInfo) in localModelsResponse {
                for (_, variant) in modelTypeInfo.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("reasoning") {
                        // Use the canonical model_id from the backend - never construct it
                        localModelsList.append(ReasoningModelInfoVM(
                            id: variant.modelId,
                            name: variant.name,
                            displayName: variant.name,
                            provider: modelType,
                            isApiModel: false
                        ))
                        #if DEBUG
                        DevLogger.shared.info("✅ Added local reasoning model: \(variant.name) with id \(variant.modelId)", context: "LiveTranscriptionViewModel")
                        #endif
                    }
                }
            }
            localModelsList.sort { $0.name < $1.name }
            
            // Load API models
            let apiModelsData = try await APIClient.shared.get("/settings/api_models/reasoning")
            struct APIModelResponse: Codable {
                let id: String
                let name: String
                let displayName: String
                let provider: String
                let isApiModel: Bool
                let description: String?
            }
            struct APIModelsResponseData: Codable {
                let status: String
                let models: [APIModelResponse]
                let apiModelsEnabled: Bool
                let currentModel: String?
            }
            let apiModelsResponse = try decoder.decode(APIModelsResponseData.self, from: apiModelsData)
            
            #if DEBUG
            DevLogger.shared.info("Found \(apiModelsResponse.models.count) API reasoning models", context: "LiveTranscriptionViewModel")
            #endif
            
            var apiModelsList: [ReasoningModelInfoVM] = []
            for model in apiModelsResponse.models {
                apiModelsList.append(ReasoningModelInfoVM(
                    id: model.id,
                    name: model.name,
                    displayName: model.displayName,
                    provider: model.provider,
                    isApiModel: true
                ))
                #if DEBUG
                DevLogger.shared.info("✅ Added API reasoning model: \(model.displayName) with id \(model.id)", context: "LiveTranscriptionViewModel")
                #endif
            }
            
            await MainActor.run {
                self.localAnalysisModels = localModelsList
                self.apiAnalysisModels = apiModelsList
                self.useApiModelsForAnalysis = modelSettings.useApiModels
                
                // Select the current reasoning model or fallback to first available
                let currentModelSelection = modelSettings.reasoningModel
                
                var displayNameToIdMap: [String: String] = [:]
                var modelIdToObjectMap: [String: ReasoningModelInfoVM] = [:]
                for model in localModelsList {
                    displayNameToIdMap[model.displayName] = model.id
                    modelIdToObjectMap[model.id] = model
                }
                for model in apiModelsList {
                    displayNameToIdMap[model.displayName] = model.id
                    modelIdToObjectMap[model.id] = model
                }
                
                if let _ = modelIdToObjectMap[currentModelSelection] {
                    self.selectedAnalysisModelId = currentModelSelection
                    #if DEBUG
                    DevLogger.shared.info("Selected analysis model using direct ID match: \(currentModelSelection)", context: "LiveTranscriptionViewModel")
                    #endif
                } else if let modelId = displayNameToIdMap[currentModelSelection] {
                    self.selectedAnalysisModelId = modelId
                    #if DEBUG
                    DevLogger.shared.info("Selected analysis model using display name match: \(currentModelSelection) -> ID: \(modelId)", context: "LiveTranscriptionViewModel")
                    #endif
                } else {
                    if modelSettings.useApiModels && !apiModelsList.isEmpty {
                        self.selectedAnalysisModelId = apiModelsList.first!.id
                    } else if !localModelsList.isEmpty {
                        self.selectedAnalysisModelId = localModelsList.first!.id
                    } else {
                        self.selectedAnalysisModelId = nil
                    }
                    #if DEBUG
                    DevLogger.shared.info("Selected fallback analysis model: \(self.selectedAnalysisModelId ?? "none")", context: "LiveTranscriptionViewModel")
                    #endif
                }
                
                self.isLoadingAnalysisModels = false
                
                #if DEBUG
                DevLogger.shared.info("Final analysis model ID: \(self.selectedAnalysisModelId ?? "none")", context: "LiveTranscriptionViewModel")
                #endif
            }
        } catch {
            await MainActor.run {
                self.isLoadingAnalysisModels = false
                #if DEBUG
                DevLogger.shared.error("Failed to load analysis models: \(error)", context: "LiveTranscriptionViewModel")
                #endif
            }
        }
    }
    
    // MARK: - Meeting-scoped progress gating

    /// True while the in-flight (or just-completed) analysis belongs to the
    /// meeting the user is currently viewing. The progress overlay and the
    /// "Analysis complete" badge are gated on this so an analysis started on
    /// meeting A does not render its bar/badge on a different meeting B the user
    /// opens mid-process (mirrors `isViewingActivePostProcessingMeeting`).
    var isViewingActiveAnalysisMeeting: Bool {
        activeAnalysisMeetingId == (selectedMeetingId ?? currentMeetingId)
    }

    // MARK: - Public Methods
    
    /// Start meeting analysis with selected modes and custom instructions.
    ///
    /// A single analysis is fired against the representative meeting id
    /// (microphone, falling back to system audio). The backend resolves the
    /// session siblings via `session_id` and merges both sides into one
    /// transcript, so the client must NOT loop per-member here: doing so caused
    /// the first completion to flip `isAnalyzing` false and silently drop the
    /// second run's completion message.
    func startMeetingAnalysis() async {
        guard let meetingId = currentMeetingId else {
            analysisStartedAutomatically = false
            #if DEBUG
            DevLogger.shared.error("No meeting ID available for analysis", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        guard !selectedAnalysisModes.isEmpty else {
            analysisStartedAutomatically = false
            #if DEBUG
            DevLogger.shared.error("No analysis modes selected", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        await MainActor.run {
            isAnalyzing = true
            analysisJustCompleted = false
            analysisProgress = 0.0
            analysisMessage = "Starting analysis..."
            currentAnalysisMode = nil
            // Retain a concrete owner so creating a fresh meeting cannot make
            // nil selection state appear to own this analysis.
            activeAnalysisMeetingId = selectedMeetingId ?? meetingId
        }
        
        #if DEBUG
        DevLogger.shared.info("Starting analysis for representative meeting \(meetingId)", context: "LiveTranscriptionViewModel")
        #endif
        
        do {
            // Start analysis job
            let port = APIClient.shared.currentPort
            let url = URL(string: "http://localhost:\(port)/meetings/\(meetingId)/analyze")!
            
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            
            // Build configuration
            let modes = Array(selectedAnalysisModes.map { $0.rawValue })
            let config = MeetingAnalysisConfig(
                modelId: selectedAnalysisModelId,
                analysisModes: modes,
                customInstructions: analysisCustomInstructions.isEmpty ? nil : analysisCustomInstructions
            )
            
            request.httpBody = try JSONEncoder().encode(config)
            
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
                throw NSError(domain: "Analysis", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to start analysis"])
            }
            
            let result = try JSONDecoder().decode([String: String].self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("Analysis started: \(result)", context: "LiveTranscriptionViewModel")
            #endif
            
            // Connect to progress WebSocket and wait for completion
            await connectAnalysisWebSocket(meetingId: meetingId)
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to start analysis: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            await MainActor.run {
                analysisMessage = "Error: \(error.localizedDescription)"
                isAnalyzing = false
                analysisStartedAutomatically = false
            }
        }
    }
    
    /// Connect to analysis progress WebSocket
    func connectAnalysisWebSocket(meetingId: String) async {
        let port = APIClient.shared.currentPort
        guard let url = URL(string: "ws://localhost:\(port)/meetings/\(meetingId)/analyze/status") else {
            #if DEBUG
            DevLogger.shared.error("Invalid WebSocket URL for analysis", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        let session = URLSession(configuration: .default)
        let webSocketTask = session.webSocketTask(with: BackendAuthorization.authorizedRequest(for: url))
        analysisWebSocketTask = webSocketTask
        
        webSocketTask.resume()
        
        #if DEBUG
        DevLogger.shared.info("Connected to analysis WebSocket for meeting \(meetingId)", context: "LiveTranscriptionViewModel")
        #endif
        
        // Listen for messages until completion
        await receiveAnalysisMessagesUntilComplete()
    }
    
    private func receiveAnalysisMessagesUntilComplete() async {
        while analysisWebSocketTask != nil && isAnalyzing {
            do {
                guard let message = try await analysisWebSocketTask?.receive() else {
                    break
                }
                
                switch message {
                case .string(let text):
                    #if DEBUG
                    DevLogger.shared.info("Analysis WebSocket message received", context: "LiveTranscriptionViewModel")
                    #endif
                    
                    if let data = text.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        await MainActor.run {
                            self.handleAnalysisMessage(json)
                        }
                    }
                    
                case .data(let data):
                    if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        await MainActor.run {
                            self.handleAnalysisMessage(json)
                        }
                    }
                    
                @unknown default:
                    break
                }
            } catch {
                #if DEBUG
                DevLogger.shared.error("Analysis WebSocket error: \(error)", context: "LiveTranscriptionViewModel")
                #endif
                await MainActor.run {
                    if isAnalyzing {  // Only update if still analyzing
                        analysisMessage = "Connection error: \(error.localizedDescription)"
                        isAnalyzing = false
                        analysisStartedAutomatically = false
                    }
                }
                break
            }
        }
    }
    
    @MainActor
    private func handleAnalysisMessage(_ json: [String: Any]) {
        let type = json["type"] as? String
        
        switch type {
        case "progress":
            handleAnalysisProgress(json)
            
        case "complete":
            handleAnalysisComplete(json)
            cleanupAnalysisWebSocket()
            
        case "error":
            let message = json["message"] as? String ?? "Unknown error"
            analysisMessage = "Error: \(message)"
            isAnalyzing = false
            analysisStartedAutomatically = false
            cleanupAnalysisWebSocket()
            
        default:
            break
        }
    }
    
    @MainActor
    private func handleAnalysisProgress(_ data: [String: Any]) {
        if let progress = data["overall_progress"] as? Double {
            analysisProgress = progress
        }
        
        if let message = data["message"] as? String {
            analysisMessage = message
        }
        
        if let mode = data["current_mode"] as? String {
            currentAnalysisMode = AnalysisMode(rawValue: mode)?.displayName
        }
        
        #if DEBUG
        DevLogger.shared.info("Analysis progress: \(Int(analysisProgress * 100))% - \(analysisMessage)", context: "LiveTranscriptionViewModel")
        #endif
    }
    
    @MainActor
    private func handleAnalysisComplete(_ data: [String: Any]) {
        // The backend saves analysis metadata before sending completion. Refresh
        // the sidebar list so its analysis counter and quick-open link receive
        // the newly persisted summary even while this meeting remains visible.
        Task {
            await loadMeetingHistory()
        }

        // Refresh the selected meeting's analysis table too, but only when the
        // analyzed meeting is the one being viewed so a background completion
        // cannot overwrite another meeting's visible analysis history.
        if isViewingActiveAnalysisMeeting, let meetingId = activeAnalysisMeetingId {
            Task {
                await loadAnalysisHistory(meetingId: meetingId)
            }
        }
        
        guard let analysisData = data["analysis"] as? [String: Any] else {
            analysisMessage = "Analysis complete but data missing"
            isAnalyzing = false
            analysisStartedAutomatically = false
            return
        }
        
        do {
            // Parse analysis result using the model's explicit snake_case keys.
            // Avoid a global convertFromSnakeCase strategy because nested result
            // models already define their own backend keys.
            let jsonData = try JSONSerialization.data(withJSONObject: analysisData)
            let decoder = JSONDecoder()
            let result = try decoder.decode(MeetingAnalysisResult.self, from: jsonData)
            
            // Filename of the just-saved analysis, sent alongside the completion
            // payload so outcomes persist to the same file this analysis reopens
            // from. Absent on older backends -> session-local behavior (AC5).
            let filename = data["filename"] as? String
            
            #if DEBUG
            DevLogger.shared.info("Analysis complete: \(result.completedModes.count) modes", context: "LiveTranscriptionViewModel")
            #endif
            
            // Show results in a separate window only when the analyzed meeting is
            // the one being viewed, so the window does not surface over an
            // unrelated meeting the user navigated to mid-analysis.
            if isViewingActiveAnalysisMeeting {
                showAnalysisResults(result, filename: filename)
            }
            
            // Update state
            analysisProgress = 1.0
            analysisMessage = "Analysis complete"
            isAnalyzing = false
            analysisStartedAutomatically = false
            // Persistent completion signal so the main window shows an
            // "Analysis complete" indicator without the user navigating away.
            analysisJustCompleted = true
            
            // Clear selections for next analysis
            selectedAnalysisModes.removeAll()
            analysisCustomInstructions = ""
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to parse analysis result: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            analysisMessage = "Error parsing results"
            isAnalyzing = false
            analysisStartedAutomatically = false
        }
    }
    
    @MainActor
    func retryFailedAnalysisModes(_ modes: [AnalysisMode], customInstructions: String?) {
        guard !modes.isEmpty, !isAnalyzing else {
            return
        }
        selectedAnalysisModes = Set(modes)
        analysisCustomInstructions = customInstructions ?? ""
        Task {
            await startMeetingAnalysis()
        }
    }

    @MainActor
    func showAnalysisResults(_ result: MeetingAnalysisResult, filename: String? = nil) {
        // Delegate to the coordinator so every attached WebKit presentation
        // (default window, legacy-QA-adjacent window) receives the same
        // analysis-result snapshot through one shared
        // MeetingAnalysisWebWindowController, instead of this view model
        // owning a SwiftUI results window directly.
        guard let coordinator = meetingSessionCoordinator else {
            #if DEBUG
            DevLogger.shared.error("showAnalysisResults called with no MeetingSessionCoordinator set", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        let dto = MeetingAnalysisResultDTOBuilder.build(result, filename: filename, transcript: analysisTranscriptLineDTOs())
        coordinator.showAnalysisResult(dto)

        #if DEBUG
        DevLogger.shared.info("Showing analysis results window", context: "LiveTranscriptionViewModel")
        #endif
    }

    /// Transcript lines for the meeting whose analysis is being shown, so the
    /// analysis window can append a `## Transcript` section to copy-all/export
    /// text. `transcriptionLines` already holds the correct meeting's combined
    /// transcript in both cases this is called from: right after live analysis
    /// completes for the actively-viewed meeting, and after selecting a past
    /// meeting from history (which populates `transcriptionLines` before its
    /// analyses become viewable). Mirrors `MeetingBridgePublisher.buildTranscript()`.
    @MainActor
    private func analysisTranscriptLineDTOs() -> [TranscriptLineDTO] {
        transcriptionLines.map { line in
            TranscriptLineDTO(
                id: line.id,
                text: line.text,
                speakerId: line.speakerID,
                isInterim: line.isInterim,
                displayStart: line.displayStart,
                timelineStartSeconds: line.timelineStartSeconds,
                timelineEndSeconds: line.timelineEndSeconds,
                source: line.source?.rawValue,
                lineComplete: line.lineComplete
            )
        }
    }
    
    // MARK: - Analysis History
    
    /// Load analysis history for a meeting
    @MainActor
    func loadAnalysisHistory(meetingId: String) async {
        isLoadingAnalysisHistory = true
        
        do {
            let history = try await APIClient.shared.listMeetingAnalyses(meetingId: meetingId)
            // Sort by timestamp descending (newest first)
            analysisHistory = history.sorted { $0.timestamp > $1.timestamp }
            isLoadingAnalysisHistory = false
            
            #if DEBUG
            DevLogger.shared.info("Loaded \(analysisHistory.count) analyses for meeting \(meetingId)", context: "LiveTranscriptionViewModel")
            #endif
        } catch {
            analysisHistory = []
            isLoadingAnalysisHistory = false
            
            #if DEBUG
            DevLogger.shared.error("Failed to load analysis history: \(error)", context: "LiveTranscriptionViewModel")
            #endif
        }
    }
    
    /// View a specific analysis from history
    @MainActor
    func viewAnalysis(meetingId: String, filename: String) async {
        guard !isLoadingAnalysisResult else { return }
        isLoadingAnalysisResult = true
        analysisResultRequestedFilename = filename
        analysisResultLoadError = nil
        meetingSessionCoordinator?.showAnalysisLoading()
        defer { isLoadingAnalysisResult = false }

        #if DEBUG
        DevLogger.shared.info("Attempting to view analysis: \(filename) for meeting: \(meetingId)", context: "LiveTranscriptionViewModel")
        #endif
        
        do {
            let analysis = try await APIClient.shared.getMeetingAnalysis(meetingId: meetingId, filename: filename)
            
            #if DEBUG
            DevLogger.shared.info("Successfully fetched analysis, showing results window", context: "LiveTranscriptionViewModel")
            #endif
            
            showAnalysisResults(analysis, filename: filename)
            analysisResultRequestedFilename = nil
            
            #if DEBUG
            DevLogger.shared.info("Analysis window should now be visible", context: "LiveTranscriptionViewModel")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to load analysis \(filename): \(error)", context: "LiveTranscriptionViewModel")
            if let decodingError = error as? DecodingError {
                DevLogger.shared.error("Decoding error details: \(decodingError)", context: "LiveTranscriptionViewModel")
            }
            #endif
            
            analysisResultLoadError = "Couldn’t open this analysis. Please try again."
        }
    }
    
    /// Delete a specific analysis
    @MainActor
    func deleteAnalysis(meetingId: String, filename: String) async {
        do {
            try await APIClient.shared.deleteMeetingAnalysis(meetingId: meetingId, filename: filename)
            
            #if DEBUG
            DevLogger.shared.info("Deleted analysis: \(filename)", context: "LiveTranscriptionViewModel")
            #endif
            
            // Reload history to reflect deletion
            await loadAnalysisHistory(meetingId: meetingId)
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to delete analysis \(filename): \(error)", context: "LiveTranscriptionViewModel")
            #endif
            // Could show an error alert here
        }
    }
    
    // MARK: - Cleanup
    
    func cleanupAnalysisWebSocket() {
        analysisWebSocketTask?.cancel(with: .goingAway, reason: nil)
        analysisWebSocketTask = nil
    }
}

