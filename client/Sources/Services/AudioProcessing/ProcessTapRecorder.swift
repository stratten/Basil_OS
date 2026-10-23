import AudioToolbox
import AVFoundation
import Foundation
import SwiftUI

@available(macOS 14.0, *)
final class ProcessTapRecorder: ObservableObject {

    let fileURL: URL
    let process: AudioProcess
    private let queue = DispatchQueue(label: "ProcessTapRecorder", qos: .userInitiated)
    private let context: String
    
    // Track recording statistics
    private var bytesWritten: UInt64 = 0
    private var startTime: Date?
    private weak var _tap: ProcessTap?

    @Published private(set) var isRecording = false
    
    // Audio level metering - using @Published
    @Published var audioLevel: Float = 0.0
    private let meterSmoothingFactor: Float = 0.15  // Lower value = more smoothing
    private var previousLevel: Float = 0.0
    // Maximum allowed change in one update to prevent jumps
    private let maxAudioLevelJump: Float = 0.3
    // Meter update rate reduction (only update UI every N samples)
    private let meterUpdateDivider: Int = 3
    private var meterUpdateCounter: Int = 0
    
    // Add callback for audio data to be sent to MeetingAudioCaptureService
    var onAudioDataAvailable: ((Data) -> Void)?
    var onRecordingFailure: ((String) -> Void)?

    // Add an error recovery mechanism
    private var consecutiveErrors = 0
    private let maxConsecutiveErrors = 5
    private var lastErrorTime: TimeInterval = 0
    private let errorResetInterval: TimeInterval = 10.0 // Reset error count after 10 seconds without errors
    private var isErrorState = false
    private var pcmBufferCreationFailureCount = 0
    private let maxPCMBufferCreationFailures = 5
    private var hasReportedPCMBufferCreationFailure = false
    private var rawDiagnosticBufferCount: UInt64 = 0

    // Persistent resampler so the underlying AVAudioConverter keeps its filter
    // state across callbacks. Only ever touched inside the `run` IO block, which
    // executes on the serial `queue`, so no locking is required.
    private let resampler = AudioStreamResampler()

    // Measures the true input sample rate from callback throughput so resampling
    // uses the real rate, not the (possibly stale) declared tap format. Only ever
    // touched inside the `run` IO block, so no locking is required.
    private let rateEstimator = AudioInputRateEstimator()

    init(fileURL: URL, tap: ProcessTap) {
        self.process = tap.process
        self.fileURL = fileURL
        self._tap = tap
        self.context = "\(String(describing: ProcessTapRecorder.self))(\(fileURL.lastPathComponent))"
        #if DEBUG
        DevLogger.shared.info("Created recorder for process '\(self.process.name)' with output file: \(fileURL.path)", context: context)
        #endif
    }

    private var tap: ProcessTap {
        get throws {
            guard let _tap else { throw "Process tap unavailable" }
            return _tap
        }
    }

    private var currentFile: AVAudioFile?

    // Define the block types
    typealias AudioDeviceIOBlock = (UnsafePointer<AudioTimeStamp>, UnsafePointer<AudioBufferList>, UnsafePointer<AudioTimeStamp>, UnsafeMutablePointer<AudioBufferList>, UnsafePointer<AudioTimeStamp>) -> Void
    typealias InvalidationHandler = () -> Void

    func start() throws {
        #if DEBUG
        DevLogger.shared.debug("start()", context: context)
        #endif
        
        guard !isRecording else { return }
        
        startTime = Date()
        bytesWritten = 0
        
        // Create audio recording file
        guard let deviceFormat = try tap.tapStreamDescription else {
            throw "Tap stream description not available"
        }
        
        #if DEBUG
        DevLogger.shared.info("Audio format: \(deviceFormat.mSampleRate) Hz, \(deviceFormat.mChannelsPerFrame) channels, \(deviceFormat.mBytesPerFrame == deviceFormat.mChannelsPerFrame * 4 ? "interleaved" : "non-interleaved")", context: context)
        #endif

        #if DEBUG
        DevLogger.shared.info("Creating audio file at \(self.fileURL.path)", context: context)
        #endif
        
        // Create AVAudioFormat from the stream description
        var formatDesc = deviceFormat // deviceFormat is already unwrapped by the previous guard
        guard let format = AVAudioFormat(streamDescription: &formatDesc) else {
            throw "Failed to create AVAudioFormat from stream description"
        }
        let tapFormat = format
        rateEstimator.reset(declaredSampleRate: tapFormat.sampleRate)
        
        // Use simpler settings based on the original working implementation
        // This matches what was in the old version that worked correctly
        let settings: [String: Any] = [
            AVFormatIDKey: formatDesc.mFormatID,
            AVSampleRateKey: format.sampleRate,
            AVNumberOfChannelsKey: format.channelCount
        ]
        
        #if DEBUG
        DevLogger.shared.info("Using format: \(formatDesc.mFormatID) at \(format.sampleRate) Hz with \(format.channelCount) channels", context: context)
        DevLogger.shared.info("Creating audio file with settings: \(settings)", context: context)
        #endif
        
        let audioFile = try AVAudioFile(
            forWriting: fileURL,
            settings: settings,
            commonFormat: .pcmFormatFloat32,
            interleaved: false
        )
        
        self.currentFile = audioFile
        
        let recordingFormat = audioFile.processingFormat
        pcmBufferCreationFailureCount = 0
        hasReportedPCMBufferCreationFailure = false
        rawDiagnosticBufferCount = 0
                
        try queue.sync {
            try self.run(
                on: self.queue,
                ioBlock: { [weak self] inNow, inInputData, inInputTime, outOutputData, inOutputTime in
                    guard let self = self, self.isRecording else { return }
                    
                    guard let extraction = RawAudioBufferListExtractor.extractPCMBuffer(
                        format: tapFormat,
                        inputData: inInputData
                    ) else {
                        self.handlePCMBufferCreationFailure(
                            tapFormat: tapFormat,
                            recordingFormat: recordingFormat,
                            inputData: inInputData
                        )
                        return
                    }

                    self.logRawAudioBufferListStats(diagnostics: extraction.diagnostics)
                    self.resetPCMBufferCreationFailuresIfNeeded()

                    let buffer = extraction.pcmBuffer
                    
                    // Handle metering
                    let level = self.calculateAudioLevel(buffer)
                    
                    // Limit maximum change to prevent jumpy meter
                    let limitedLevel = self.previousLevel + min(self.maxAudioLevelJump, max(-self.maxAudioLevelJump, level - self.previousLevel))
                    
                    // Apply smoothing
                    let smoothedLevel = (self.meterSmoothingFactor * limitedLevel) + ((1 - self.meterSmoothingFactor) * self.previousLevel)
                    
                    // Log significant levels
                    if level > 0.05 {
                        // Logging removed to reduce noise
                    }
                    
                    // Always update previousLevel for calculations
                    self.previousLevel = smoothedLevel
                    
                    // Increment counter and check if we should update UI
                    self.meterUpdateCounter = (self.meterUpdateCounter + 1) % self.meterUpdateDivider
                    
                    // Only update UI every N samples to reduce visual jitter
                    if self.meterUpdateCounter == 0 {
                        DispatchQueue.main.async {
                            self.audioLevel = smoothedLevel
                        }
                    }
                    
                    // Write to the local diagnostic file when possible. Live
                    // transcription delivery below must not depend on this write.
                    do {
                        if let file = self.currentFile {
                            try file.write(from: buffer)
                            
                            // Update bytes written count
                            let bytesInFrame = UInt64(buffer.frameLength * UInt32(buffer.format.streamDescription.pointee.mBytesPerFrame))
                            self.bytesWritten += bytesInFrame
                        }
                    } catch {
                        DevLogger.shared.error("Failed to write audio buffer: \(error)", context: self.context)
                    }

                    // IMPROVED: Send audio data to callback
                    // Use the specialized transcription format method for the callback
                    if let callback = self.onAudioDataAvailable {
                        #if DEBUG
                        // Add useful diagnostic logging to track audio data flow
                        if Int.random(in: 1...50) == 1 { // Log occasionally to avoid flooding
                            DevLogger.shared.info("Processing audio buffer: \(buffer.frameLength) frames", context: self.context)
                        }
                        #endif
                        
                        // Convert buffer to transcription data format (16kHz mono float32),
                        // resampling from the measured true rate. In the common case the
                        // estimate equals the buffer's declared rate and this is a no-op.
                        let estimatedRate = self.rateEstimator.observe(frameCount: buffer.frameLength)
                        let bufferForTranscription = estimatedRate != buffer.format.sampleRate
                            ? (buffer.relabeled(sampleRate: estimatedRate) ?? buffer)
                            : buffer
                        let transcriptionData = self.resampler.resampledData(from: bufferForTranscription)
                        if let transcriptionData, !transcriptionData.isEmpty {
                            #if DEBUG
                            if Int.random(in: 1...100) == 1 { // Log rarely
                                DevLogger.shared.info("Sending \(transcriptionData.count) bytes of transcription data", context: self.context)
                            }
                            #endif
                            
                            // Send data to callback on main thread to ensure consistent delivery
                            DispatchQueue.main.async {
                                // Reset error counter if we haven't had errors in a while
                                let currentTime = Date().timeIntervalSince1970
                                if currentTime - self.lastErrorTime > self.errorResetInterval {
                                    self.consecutiveErrors = 0
                                    if self.isErrorState {
                                        self.isErrorState = false
                                        #if DEBUG
                                        DevLogger.shared.info("Audio data delivery recovered after error state", context: self.context)
                                        #endif
                                    }
                                }
                                
                                // Attempt to send data with error tracking
                                callback(transcriptionData)
                            }
                        } else if transcriptionData == nil {
                            // A nil result is a hard conversion failure. We do NOT fall
                            // back to raw buffer bytes: those are native-rate stereo
                            // audio that the transcription pipeline cannot use.
                            #if DEBUG
                            DevLogger.shared.warning("Failed to convert audio buffer to transcription data", context: self.context)
                            #endif
                        }
                        // An empty (non-nil) result is normal converter priming; skip silently.
                    }
                },
                invalidationHandler: { [weak self] in
                    self?.handleInvalidation()
                }
            )
        }
        
        self.isRecording = true
        
        #if DEBUG
        DevLogger.shared.info("Recording started successfully for \(self.process.name)", context: context)
        #endif
    }

    func run(on queue: DispatchQueue, ioBlock: @escaping AudioDeviceIOBlock, invalidationHandler: InvalidationHandler?) throws {
        #if DEBUG
        DevLogger.shared.info("Running tap for process: \(self.process.name)", context: context)
        #endif

        // Get the tap instance
        let tap = try self.tap
        
        // Convert our invalidation handler to the type ProcessTap expects
        let tapInvalidationHandler: ProcessTap.InvalidationHandler = { _ in
            invalidationHandler?()
        }
        
        try tap.run(on: queue, ioBlock: ioBlock, invalidationHandler: tapInvalidationHandler)
    }
    
    func stop() {
        #if DEBUG
        DevLogger.shared.debug("stop()", context: context)
        #endif
        
        guard isRecording else { return }

        #if DEBUG
        DevLogger.shared.info("Stopping recording from \(self.process.name)", context: context)
        #endif
        
        do {
            try tap.invalidate()
                        
            guard let startTime = startTime else { return }
            let duration = Date().timeIntervalSince(startTime)
            
            #if DEBUG
            let formattedDuration = String(format: "%.2f", duration)
            let formattedBytes = String(format: "%.2f", Double(bytesWritten) / 1_048_576)
            DevLogger.shared.info("Recording completed: \(formattedDuration) seconds, \(bytesWritten) bytes written", context: context)
            DevLogger.shared.info("Output file: \(fileURL.path), size: \(formattedBytes) MB", context: context)
            #endif
            
            self.isRecording = false
            self.currentFile = nil
            self.startTime = nil
            
            // Reset audio level
            DispatchQueue.main.async {
                self.audioLevel = 0.0
                self.previousLevel = 0.0
            }
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to stop recording: \(error)", context: context)
            #endif
        }
    }
    
    private func handleInvalidation() {
        #if DEBUG
        DevLogger.shared.info("Recording invalidated for \(self.process.name)", context: context)
        #endif
        
        // If we're still recording when invalidated, clean up
        if isRecording {
            isRecording = false
            currentFile = nil
            
            // Reset audio level
            DispatchQueue.main.async {
                self.audioLevel = 0.0
                self.previousLevel = 0.0
            }
        }
    }

    private func logRawAudioBufferListStats(diagnostics: RawAudioBufferListExtractionDiagnostics) {
        rawDiagnosticBufferCount += 1
        guard rawDiagnosticBufferCount <= 5 || rawDiagnosticBufferCount % 250 == 0 else {
            return
        }

        #if DEBUG
        DevLogger.shared.info(
            "Raw selected-process AudioBufferList \(rawDiagnosticBufferCount): \(diagnostics.summary)",
            context: context
        )
        #endif
    }

    private func handlePCMBufferCreationFailure(
        tapFormat: AVAudioFormat,
        recordingFormat: AVAudioFormat,
        inputData: UnsafePointer<AudioBufferList>
    ) {
        pcmBufferCreationFailureCount += 1

        #if DEBUG
        if pcmBufferCreationFailureCount == 1 || pcmBufferCreationFailureCount == maxPCMBufferCreationFailures {
            DevLogger.shared.error(
                """
                Failed to create PCM buffer for selected-process audio.
                failure_count=\(pcmBufferCreationFailureCount)
                tap_format=\(RawAudioBufferListExtractor.describeAudioFormat(tapFormat))
                recording_format=\(RawAudioBufferListExtractor.describeAudioFormat(recordingFormat))
                buffer_list=\(RawAudioBufferListExtractor.describeAudioBufferList(inputData))
                """,
                context: context
            )
        }
        #endif

        guard pcmBufferCreationFailureCount >= maxPCMBufferCreationFailures,
              !hasReportedPCMBufferCreationFailure else {
            return
        }

        hasReportedPCMBufferCreationFailure = true
        let message = "Could not read audio buffers from \(process.name)."
        DispatchQueue.main.async { [weak self] in
            self?.onRecordingFailure?(message)
        }
    }

    private func resetPCMBufferCreationFailuresIfNeeded() {
        guard pcmBufferCreationFailureCount > 0 else { return }

        #if DEBUG
        DevLogger.shared.info(
            "PCM buffer creation recovered after \(pcmBufferCreationFailureCount) failure(s)",
            context: context
        )
        #endif

        pcmBufferCreationFailureCount = 0
        hasReportedPCMBufferCreationFailure = false
    }
    
    private func calculateAudioLevel(_ buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData else { return 0.0 }
        
        let channelCount = Int(buffer.format.channelCount)
        let frameLength = Int(buffer.frameLength)
        
        // No buffer details logging
        
        var sumSquares: Float = 0.0
        // Process all samples for accuracy
        for channel in 0..<channelCount {
            let data = channelData[channel]
            for frame in 0..<frameLength {
                let sample = data[frame]
                sumSquares += sample * sample
            }
        }

        return AudioLevelNormalizer.normalizedLevel(
            sumOfSquares: sumSquares,
            sampleCount: frameLength * channelCount
        )
    }
}
