import AVFoundation
import Foundation

extension AudioCaptureService {
    static var activeRecordingOwners: [String] {
        Array(Set(activeRecordingOwnersByInstance.values)).sorted()
    }

    static func blockingRecordingOwners() -> [String] {
        activeRecordingOwners
    }

    func reserveRecordingAdmission(flowContext: String?) throws {
        let owner = flowContext ?? "unspecifiedAudioCapture"
        guard Self.activeRecordingOwnersByInstance[recordingRegistryId] == nil else {
            throw AudioCaptureError.configurationFailed("Audio recording is already starting or active.")
        }
        guard Self.activeRecordingOwnersByInstance.isEmpty else {
            throw AudioCaptureError.configurationFailed("Microphone is already in use by \(Self.activeRecordingOwners.joined(separator: ", ")).")
        }
        Self.activeRecordingOwnersByInstance[recordingRegistryId] = owner
    }

    func markRecordingActive(flowContext: String?) {
        Self.activeRecordingOwnersByInstance[recordingRegistryId] = flowContext ?? "unspecifiedAudioCapture"
    }

    func markRecordingInactive() {
        Self.activeRecordingOwnersByInstance.removeValue(forKey: recordingRegistryId)
    }

    // Public getter for last recorded audio data
    public var lastRecordingData: Data? {
        return recordingData.isEmpty ? nil : recordingData
    }
    
    // Public method to clear recording data (for cleanup after processing)
    public func clearRecordingData() {
        recordingData = Data()
        #if DEBUG
        DevLogger.shared.info("[AUDIO CAPTURE] Recording data cleared manually", context: "AudioCaptureService")
        #endif
    }

    @MainActor
    func startRecording(flowContext: String? = nil) async throws {
        guard activeRecordingStartID == nil, !isRecording else {
            throw AudioCaptureError.configurationFailed("Audio recording is already starting or active.")
        }

        try reserveRecordingAdmission(flowContext: flowContext)
        let startID = UUID()
        let startupBeganAt = CFAbsoluteTimeGetCurrent()
        activeRecordingStartID = startID
        currentFlowContext = flowContext
        silentRetryCount = 0
        audioTapDiagnosticBufferCount = 0
        error = nil
        recordingData = Data()

        do {
            try await checkPermissionsAndSetup()
            try validateRecordingStartup(startID: startID)
            let permissionReadyAt = CFAbsoluteTimeGetCurrent()
            try await ensureRecordingPipelinePrepared()
            try validateRecordingStartup(startID: startID)
            let pipelineReadyAt = CFAbsoluteTimeGetCurrent()

            if let validationSyntheticAudioSource {
                try validationSyntheticAudioSource.start { [weak self] buffer, sourceFormat in
                    self?.processAudioBuffer(buffer, sourceFormat: sourceFormat)
                }
            } else {
                guard let engine = audioEngine else {
                    throw AudioCaptureError.engineNotRunning
                }
                try await audioEngineOperationQueue.start(engine)
            }
            try validateRecordingStartup(startID: startID)
            let engineStartedAt = CFAbsoluteTimeGetCurrent()

            markRecordingActive(flowContext: currentFlowContext)
            isRecording = true
            try await waitForFirstCapturedBuffer(startID: startID)
            try validateRecordingStartup(startID: startID)
            activeRecordingStartID = nil
            let firstBufferReadyAt = CFAbsoluteTimeGetCurrent()
            #if DEBUG
            DevLogger.shared.info(
                String(
                    format: "Capture startup stages: permission=%.3fs preparation=%.3fs source_start=%.3fs first_buffer=%.3fs total=%.3fs synthetic=%@",
                    permissionReadyAt - startupBeganAt,
                    pipelineReadyAt - permissionReadyAt,
                    engineStartedAt - pipelineReadyAt,
                    firstBufferReadyAt - engineStartedAt,
                    firstBufferReadyAt - startupBeganAt,
                    validationSyntheticAudioSource == nil ? "false" : "true"
                ),
                context: "AudioCaptureService"
            )
            #endif
            logAudioEngineDiagnostics(context: "AudioCaptureService.startRecording")
        } catch {
            if activeRecordingStartID == startID {
                activeRecordingStartID = nil
            }
            cleanupCancelledRecordingStartup()
            throw error
        }
    }

    func validateRecordingStartup(startID: UUID) throws {
        try Task.checkCancellation()
        guard activeRecordingStartID == startID else {
            throw CancellationError()
        }
    }

    func cancelRecordingStartup() {
        guard activeRecordingStartID != nil else { return }
        activeRecordingStartID = nil
        cleanupCancelledRecordingStartup()
    }

    func cleanupCancelledRecordingStartup() {
        let continuation = firstBufferContinuation
        firstBufferContinuation = nil
        firstBufferStartID = nil
        continuation?.resume(throwing: CancellationError())
        markRecordingInactive()
        isRecording = false
        scheduleRecordingPipelineRepreparation()
        recordingData = Data()
        audioLevel = 0.0
        clearContextInfo()
        currentFlowContext = nil
    }

    func waitForFirstCapturedBuffer(startID: UUID) async throws {
        try await withCheckedThrowingContinuation {
            (continuation: CheckedContinuation<Void, Error>) in
            guard activeRecordingStartID == startID else {
                continuation.resume(throwing: CancellationError())
                return
            }
            firstBufferStartID = startID
            firstBufferContinuation = continuation
        }
    }

    func signalFirstCapturedBuffer() {
        guard let startID = activeRecordingStartID,
              firstBufferStartID == startID,
              let continuation = firstBufferContinuation else { return }
        firstBufferContinuation = nil
        firstBufferStartID = nil
        continuation.resume()
    }

    func scheduleRecordingPipelineRepreparation() {
        invalidateRecordingPipelinePreparation()
        if let validationSyntheticAudioSource {
            validationSyntheticAudioSource.stop()
            isAudioTapPrepared = true
            return
        }
        guard let engine = audioEngine else { return }

        let generation = recordingPipelineGeneration
        let preparationTask = Task { @MainActor [weak self] in
            guard let self else { throw CancellationError() }
            await self.audioEngineOperationQueue.pauseAndRemoveTap(engine)
            try Task.checkCancellation()
            guard self.recordingPipelineGeneration == generation,
                  self.permissionGranted else {
                throw CancellationError()
            }
            try await self.setupAudioEngineAsync(generation: generation)
        }
        recordingPipelinePreparationTask = preparationTask
        Task { @MainActor [weak self] in
            do {
                try await preparationTask.value
                guard let self,
                      self.recordingPipelineGeneration == generation else { return }
                self.recordingPipelinePreparationTask = nil
            } catch {
                guard let self,
                      self.recordingPipelineGeneration == generation else { return }
                self.recordingPipelinePreparationTask = nil
                self.isAudioTapPrepared = false
            }
        }
    }

    @MainActor
    func stopRecording(sendAudioData: Bool = true, flowContext: String? = nil, context: [String: Any]? = nil) {
        // If a context is provided, use it; otherwise, keep the current one
        if let flowContext = flowContext {
            self.currentFlowContext = flowContext
        }
        if activeRecordingStartID != nil {
            cancelRecordingStartup()
            return
        }
        guard isRecording else {
            #if DEBUG
                DevLogger.shared.warning("stopRecording called but not recording", context: "AudioCapture")
            #endif
            return
        }
        
        #if DEBUG
            DevLogger.shared.info("Setting isRecording to false", context: "AudioCapture")
            DevLogger.shared.info("Before isRecording change - current value: \(isRecording)", context: "AudioCapture")
        #endif
        
        markRecordingInactive()
        isRecording = false
        
        #if DEBUG
            DevLogger.shared.info("After isRecording change - new value: \(isRecording)", context: "AudioCapture")
            DevLogger.shared.info("⚠️ ICON CHECK: Status bar should now be updated to non-recording icon", context: "AudioCapture")
        #endif
        
        scheduleRecordingPipelineRepreparation()

        // Send the complete recording only if sendAudioData is true
        if sendAudioData && !recordingData.isEmpty {
            #if DEBUG
                DevLogger.shared.info("Prepared to send \(recordingData.count) bytes for context: \(currentFlowContext ?? "nil")", context: "AudioCaptureService")
            #endif
            if currentFlowContext == "assistantSession" {
                #if DEBUG
                    DevLogger.shared.info("[AUDIO SEND] Skipping WebSocket send for assistantSession context", context: "AudioCaptureService")
                #endif
            } else {
                // Get active application information
                let appName = contextInfo["app_name"] ?? nil
                let windowTitle = contextInfo["window_title"] ?? nil
                let taskCategory = contextInfo["task_category"] ?? nil

                #if DEBUG
                    DevLogger.shared.info("[AUDIO SEND] Calling WebSocketService.sendAudioDataWithContext with flowContext: \(currentFlowContext ?? "nil") and data size: \(recordingData.count)", context: "AudioCaptureService")
                #endif
                if let ws = webSocketService {
                    #if DEBUG
                        DevLogger.shared.info("[AUDIO SEND] WebSocketService isConnected: \(ws.isConnected)", context: "AudioCaptureService")
                    #endif
                } else {
                    #if DEBUG
                        DevLogger.shared.error("[AUDIO SEND] WebSocketService is nil", context: "AudioCaptureService")
                    #endif
                }
                webSocketService?.transcription.sendAudioDataWithContext(
                    recordingData,
                    appName: appName,
                    windowTitle: windowTitle,
                    taskCategory: taskCategory,
                    flowContext: currentFlowContext,
                    clarificationContext: context
                )
            }
        } else if !sendAudioData {
            #if DEBUG
                DevLogger.shared.info("sendAudioData is false, not sending audio data (\(recordingData.count) bytes)", context: "AudioCaptureService")
            #endif
        } else {
            #if DEBUG
                DevLogger.shared.warning("No recording data to send", context: "AudioCaptureService")
            #endif
        }
        
        // Clear recording data only for contexts that don't need to preserve audio for later access
        // Preserve data for flows that upload the finalized recording after
        // `stopRecording` returns rather than through this service's WebSocket path.
        #if DEBUG
        DevLogger.shared.info("[AUDIO CAPTURE] 🔍 stopRecording called with context: '\(currentFlowContext ?? "nil")', data size: \(recordingData.count) bytes", context: "AudioCaptureService")
        #endif
        
        if currentFlowContext != "assistantSession"
            && currentFlowContext != "clarification"
            && currentFlowContext != "agentTask"
            && currentFlowContext != "basil_board_home"
            && currentFlowContext != "basil_board_conversation" {
            #if DEBUG
            DevLogger.shared.info("[AUDIO CAPTURE] ♻️ Clearing recording data for context '\(currentFlowContext ?? "nil")'", context: "AudioCaptureService")
            #endif
            recordingData = Data()
        } else {
            #if DEBUG
            DevLogger.shared.info("[AUDIO CAPTURE] 💾 Preserving recording data for context '\(currentFlowContext ?? "nil")' - \(recordingData.count) bytes", context: "AudioCaptureService")
            #endif
        }
        
        // Clear context info after sending
        clearContextInfo()
        // Reset flow context now that audio has been sent or skipped
        currentFlowContext = nil
        logAudioEngineDiagnostics(context: "AudioCaptureService.stopRecording")

    }
}

