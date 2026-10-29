import AVFoundation
import Foundation

extension AudioCaptureService {
    @MainActor
    func prepareRecordingPipelineIfAuthorized() async {
        guard permissionGranted,
              activeRecordingStartID == nil,
              !isRecording else { return }

        do {
            try await ensureRecordingPipelinePrepared()
        } catch is CancellationError {
            return
        } catch {
            #if DEBUG
            DevLogger.shared.warning(
                "Idle microphone preparation failed and will retry on start: \(error)",
                context: "AudioCaptureService"
            )
            #endif
        }
    }

    @MainActor
    func ensureRecordingPipelinePrepared() async throws {
        if validationSyntheticAudioSource != nil {
            isAudioTapPrepared = true
            return
        }

        if isAudioTapPrepared {
            return
        }
        if let existingTask = recordingPipelinePreparationTask {
            try await existingTask.value
            return
        }

        let generation = recordingPipelineGeneration
        let task = Task { @MainActor [weak self] in
            guard let self else { throw CancellationError() }
            try await self.setupAudioEngineAsync(generation: generation)
        }
        recordingPipelinePreparationTask = task

        do {
            try await task.value
            if recordingPipelineGeneration == generation {
                recordingPipelinePreparationTask = nil
            }
        } catch {
            if recordingPipelineGeneration == generation {
                recordingPipelinePreparationTask = nil
                isAudioTapPrepared = false
            }
            throw error
        }
    }

    @MainActor
    func invalidateRecordingPipelinePreparation() {
        recordingPipelineGeneration += 1
        recordingPipelinePreparationTask?.cancel()
        recordingPipelinePreparationTask = nil
        isAudioTapPrepared = false
    }

    @MainActor
    func setupAudioEngineAsync(generation: Int) async throws {
        guard let engine = audioEngine,
              let format = audioFormat else {
            #if DEBUG
            DevLogger.shared.error(
                "Audio engine or target format is unavailable during preparation",
                context: "AudioCaptureService"
            )
            #endif
            throw AudioCaptureError.formatError
        }

        #if DEBUG
        DevLogger.shared.info(
            "[AUDIO CAPTURE] Queuing tap installation and engine preparation",
            context: "AudioCaptureService"
        )
        #endif

        try await audioEngineOperationQueue.installAndPrepareTap(
            engine: engine,
            targetFormat: format
        ) { [weak self] buffer, sourceFormat in
            self?.processAudioBuffer(buffer, sourceFormat: sourceFormat)
        }
        try Task.checkCancellation()
        guard recordingPipelineGeneration == generation else {
            throw CancellationError()
        }
        isAudioTapPrepared = true

        #if DEBUG
        DevLogger.shared.info(
            "Audio tap installed and engine prepared off the main actor",
            context: "AudioCaptureService"
        )
        #endif
    }
}

