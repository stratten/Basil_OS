import AVFoundation
import Foundation

extension AudioCaptureService {
    // MARK: - Audio Setup Methods
    
    func setupAudioSession() {
        #if DEBUG
            DevLogger.shared.info("Setting up audio session", context: "AudioCapture")
        #endif
        
        // macOS doesn't use AVAudioSession - audio session is managed by the system
        #if DEBUG
            DevLogger.shared.info("Audio session setup not needed on macOS", context: "AudioCapture")
        #endif
    }
    
    func setupAudioEngine() {
        #if DEBUG
            DevLogger.shared.info("Setting up audio engine", context: "AudioCapture")
        #endif
        
        // Basic initialization - actual setup happens when recording starts
        // NOTE: Do NOT access audioEngine.inputNode here - doing so triggers the TCC
        // microphone permission dialog on macOS. Defer inputNode access until recording starts.
        audioEngine = AVAudioEngine()
        #if DEBUG
            DevLogger.shared.info("[AUDIO CAPTURE] setupAudioEngine created engine at pointer: \(Unmanaged.passUnretained(audioEngine!).toOpaque())", context: "AudioCaptureService")
            // inputNode access deferred to startRecording() to avoid early permission prompt
        #endif
        // Add observer for engine configuration changes
        // Use the correct notification name for AVAudioEngine configuration changes on macOS/iOS
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleEngineConfigurationChange(_:)),
            name: .AVAudioEngineConfigurationChange,
            object: audioEngine
        )
        
        // NOTE: logAudioEngineDiagnostics accesses inputNode, so defer until recording starts
        
        #if DEBUG
            DevLogger.shared.info("Audio engine setup complete", context: "AudioCapture")
        #endif
    }

    // MARK: - Engine Configuration Change Handling
    @objc func handleEngineConfigurationChange(_ notification: Notification) {
        guard let engine = notification.object as? AVAudioEngine else { return }
        invalidateRecordingPipelinePreparation()
        #if DEBUG
        let nodeCount = engine.attachedNodes.count
        DevLogger.shared.info("[AUDIO CAPTURE] Engine configuration changed. isRunning: \(engine.isRunning), attachedNodes: \(nodeCount)", context: "AudioCaptureService")
        #endif
        guard isRecording, !engine.isRunning else { return }

        // A configuration change routinely fires immediately after
        // `engine.start()` while capture is still in its startup phase
        // (suspended in `waitForFirstCapturedBuffer`). Treating that transient
        // settling notification as a device interruption tore the just-started
        // recording down and surfaced a `CancellationError` ("Failed to start
        // refinement recording"). During startup, recover the engine so the
        // first buffer can arrive instead of aborting; a genuine device loss
        // still fails through the recovery catch below.
        if activeRecordingStartID != nil {
            let generation = recordingPipelineGeneration
            Task { @MainActor [weak self] in
                await self?.recoverRecordingStartupAfterConfigurationChange(
                    engine: engine,
                    generation: generation
                )
            }
            return
        }

        error = "Microphone recording was interrupted."
        stopRecording(sendAudioData: false)
    }

    /// Reinstalls the input tap and restarts the engine after a configuration
    /// change that interrupted recording startup. On success the pending
    /// `waitForFirstCapturedBuffer` continuation resumes once buffers flow
    /// again; on failure (e.g. the input device was actually lost) the startup
    /// is aborted with the standard interruption error. The `generation` guard
    /// ensures only the most recent configuration change drives the restart
    /// when several arrive in quick succession.
    @MainActor
    func recoverRecordingStartupAfterConfigurationChange(
        engine: AVAudioEngine,
        generation: Int
    ) async {
        guard activeRecordingStartID != nil,
              !engine.isRunning,
              let format = audioFormat else { return }

        do {
            try await audioEngineOperationQueue.installAndPrepareTap(
                engine: engine,
                targetFormat: format
            ) { [weak self] buffer, sourceFormat in
                self?.processAudioBuffer(buffer, sourceFormat: sourceFormat)
            }
            guard recordingPipelineGeneration == generation,
                  activeRecordingStartID != nil else { return }
            try await audioEngineOperationQueue.start(engine)
            guard recordingPipelineGeneration == generation,
                  activeRecordingStartID != nil else { return }
            isAudioTapPrepared = true
            #if DEBUG
            DevLogger.shared.info(
                "[AUDIO CAPTURE] Recovered capture after startup configuration change",
                context: "AudioCaptureService"
            )
            #endif
        } catch {
            guard activeRecordingStartID != nil else { return }
            #if DEBUG
            DevLogger.shared.error(
                "[AUDIO CAPTURE] Failed to recover capture after startup configuration change: \(error)",
                context: "AudioCaptureService"
            )
            #endif
            self.error = "Microphone recording was interrupted."
            stopRecording(sendAudioData: false)
        }
    }
}

