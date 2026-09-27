import AudioToolbox
import AVFoundation
import Combine
import Foundation

@available(macOS 14.0, *)
final class SystemOutputTap {
    typealias InvalidationHandler = (SystemOutputTap) -> Void

    private let context = "SystemOutputTap"
    private(set) var errorMessage: String?

    private var processTapID: AudioObjectID = .unknown
    private var aggregateDeviceID: AudioObjectID = .unknown
    private var deviceProcID: AudioDeviceIOProcID?
    private var invalidationHandler: InvalidationHandler?
    private(set) var tapStreamDescription: AudioStreamBasicDescription?
    private(set) var activated = false

    @MainActor
    func activate() {
        guard !activated else { return }
        activated = true
        errorMessage = nil

        do {
            if #available(macOS 14.2, *) {
                try prepare()
            } else {
                throw "Global system output capture requires macOS 14.2 or later"
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to activate global system output tap: \(error)", context: context)
            #endif
            errorMessage = error.localizedDescription
        }
    }

    func invalidate() {
        guard activated else { return }
        defer { activated = false }

        invalidationHandler?(self)
        invalidationHandler = nil

        if aggregateDeviceID.isValid {
            var err = AudioDeviceStop(aggregateDeviceID, deviceProcID)
            if err != noErr {
                #if DEBUG
                DevLogger.shared.warning("Failed to stop global aggregate device: \(err)", context: context)
                #endif
            }

            if let deviceProcID {
                err = AudioDeviceDestroyIOProcID(aggregateDeviceID, deviceProcID)
                if err != noErr {
                    #if DEBUG
                    DevLogger.shared.warning("Failed to destroy global tap I/O proc: \(err)", context: context)
                    #endif
                }
                self.deviceProcID = nil
            }

            err = AudioHardwareDestroyAggregateDevice(aggregateDeviceID)
            if err != noErr {
                #if DEBUG
                DevLogger.shared.warning("Failed to destroy global aggregate device: \(err)", context: context)
                #endif
            }
            aggregateDeviceID = .unknown
        }

        if processTapID.isValid {
            if #available(macOS 14.2, *) {
                let err = AudioHardwareDestroyProcessTap(processTapID)
                if err != noErr {
                    #if DEBUG
                    DevLogger.shared.warning("Failed to destroy global system output tap: \(err)", context: context)
                    #endif
                }
            }
            processTapID = .unknown
        }
    }

    @available(macOS 14.2, *)
    private func prepare() throws {
        let excludedProcessIDs = Self.currentProcessObjectID().map { [$0] } ?? []
        let tapDescription = CATapDescription(stereoGlobalTapButExcludeProcesses: excludedProcessIDs)
        let tapUUID = UUID()
        tapDescription.uuid = tapUUID
        tapDescription.name = "Basil System Audio"
        tapDescription.muteBehavior = .unmuted

        var tapID: AUAudioObjectID = .unknown
        var err = AudioHardwareCreateProcessTap(tapDescription, &tapID)
        guard err == noErr else {
            throw "Global system output tap creation failed with error \(err)"
        }
        processTapID = tapID

        let systemOutputID = try AudioObjectID.readDefaultSystemOutputDevice()
        let outputUID = try systemOutputID.readDeviceUID()
        let aggregateUID = UUID().uuidString

        tapStreamDescription = try tapID.readAudioTapStreamBasicDescription()

        let description: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Basil System Audio",
            kAudioAggregateDeviceUIDKey: aggregateUID,
            kAudioAggregateDeviceMainSubDeviceKey: outputUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [
                [
                    kAudioSubDeviceUIDKey: outputUID
                ]
            ],
            kAudioAggregateDeviceTapListKey: [
                [
                    kAudioSubTapDriftCompensationKey: true,
                    kAudioSubTapUIDKey: tapDescription.uuid.uuidString
                ]
            ]
        ]

        err = AudioHardwareCreateAggregateDevice(description as CFDictionary, &aggregateDeviceID)
        guard err == noErr else {
            AudioHardwareDestroyProcessTap(processTapID)
            processTapID = .unknown
            throw "Failed to create global system output aggregate device: \(err)"
        }

        #if DEBUG
        DevLogger.shared.info("Global system output tap activated with aggregate device \(aggregateDeviceID)", context: context)
        #endif
    }

    func run(on queue: DispatchQueue, ioBlock: @escaping AudioDeviceIOBlock, invalidationHandler: @escaping InvalidationHandler) throws {
        guard activated else { throw "Global system output tap is not active" }
        guard self.invalidationHandler == nil else { throw "Global system output tap is already running" }

        self.invalidationHandler = invalidationHandler

        var err = AudioDeviceCreateIOProcIDWithBlock(&deviceProcID, aggregateDeviceID, queue, ioBlock)
        guard err == noErr else {
            throw "Failed to create global system output I/O proc: \(err)"
        }

        err = AudioDeviceStart(aggregateDeviceID, deviceProcID)
        guard err == noErr else {
            throw "Failed to start global system output aggregate device: \(err)"
        }
    }

    private static func currentProcessObjectID() -> AudioObjectID? {
        try? AudioObjectID.translatePIDToProcessObjectID(pid: pid_t(ProcessInfo.processInfo.processIdentifier))
    }

    deinit {
        invalidate()
    }
}

@available(macOS 14.0, *)
final class SystemOutputTapRecorder: ObservableObject {
    let fileURL: URL
    private let tap: SystemOutputTap
    private let queue = DispatchQueue(label: "SystemOutputTapRecorder", qos: .userInitiated)
    private let context = "SystemOutputTapRecorder"

    @Published private(set) var isRecording = false
    @Published var audioLevel: Float = 0.0

    var onAudioDataAvailable: ((Data) -> Void)?

    private var currentFile: AVAudioFile?
    private var bytesWritten: UInt64 = 0
    private var deliveredBufferCount: UInt64 = 0
    private var startTime: Date?
    private var previousLevel: Float = 0.0
    private let meterSmoothingFactor: Float = 0.15
    private let maxAudioLevelJump: Float = 0.3
    private let meterUpdateDivider: Int = 3
    private var meterUpdateCounter: Int = 0
    private var pcmBufferCreationFailureCount = 0
    private var rawDiagnosticBufferCount: UInt64 = 0

    // Persistent resampler so the underlying AVAudioConverter keeps its filter
    // state across callbacks. Only ever touched inside the `tap.run` IO block,
    // which runs on the serial `queue`, so no locking is required.
    private let resampler = AudioStreamResampler()

    // Measures the true input sample rate from callback throughput so resampling
    // uses the real rate, not the (possibly stale) declared tap format. Only ever
    // touched inside the `tap.run` IO block, so no locking is required.
    private let rateEstimator = AudioInputRateEstimator()

    init(fileURL: URL, tap: SystemOutputTap) {
        self.fileURL = fileURL
        self.tap = tap
    }

    func start() throws {
        guard !isRecording else { return }
        startTime = Date()
        bytesWritten = 0
        deliveredBufferCount = 0

        guard var formatDescription = tap.tapStreamDescription,
              let format = AVAudioFormat(streamDescription: &formatDescription) else {
            throw "Global system output tap stream description is unavailable"
        }
        let tapFormat = format
        rateEstimator.reset(declaredSampleRate: tapFormat.sampleRate)

        let settings: [String: Any] = [
            AVFormatIDKey: formatDescription.mFormatID,
            AVSampleRateKey: format.sampleRate,
            AVNumberOfChannelsKey: format.channelCount
        ]

        let audioFile = try AVAudioFile(
            forWriting: fileURL,
            settings: settings,
            commonFormat: .pcmFormatFloat32,
            interleaved: false
        )
        currentFile = audioFile
        pcmBufferCreationFailureCount = 0
        rawDiagnosticBufferCount = 0

        isRecording = true
        try tap.run(
            on: queue,
            ioBlock: { [weak self] _, inInputData, _, _, _ in
                guard let self, self.isRecording else { return }

                guard let extraction = RawAudioBufferListExtractor.extractPCMBuffer(
                    format: tapFormat,
                    inputData: inInputData
                ) else {
                    self.handlePCMBufferCreationFailure(tapFormat: tapFormat, inputData: inInputData)
                    return
                }

                self.logRawAudioBufferListStats(diagnostics: extraction.diagnostics)
                self.resetPCMBufferCreationFailuresIfNeeded()

                let buffer = extraction.pcmBuffer
                self.updateMeter(from: buffer)

                do {
                    try self.currentFile?.write(from: buffer)
                    let bytesInFrame = UInt64(buffer.frameLength * UInt32(buffer.format.streamDescription.pointee.mBytesPerFrame))
                    self.bytesWritten += bytesInFrame
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("Failed writing global system output buffer: \(error)", context: self.context)
                    #endif
                }

                // Resample using the measured true rate. In the common case the
                // estimate equals the buffer's declared rate and this is a no-op.
                let estimatedRate = self.rateEstimator.observe(frameCount: buffer.frameLength)
                let bufferForTranscription = estimatedRate != buffer.format.sampleRate
                    ? (buffer.relabeled(sampleRate: estimatedRate) ?? buffer)
                    : buffer
                let transcriptionData = self.resampler.resampledData(from: bufferForTranscription)
                if let transcriptionData, !transcriptionData.isEmpty {
                    self.deliveredBufferCount += 1
                    #if DEBUG
                    if self.deliveredBufferCount == 1 || self.deliveredBufferCount % 250 == 0 {
                        DevLogger.shared.info(
                            "Global system output buffer \(self.deliveredBufferCount): frames=\(buffer.frameLength), bytes=\(transcriptionData.count), level=\(self.audioLevel)",
                            context: self.context
                        )
                    }
                    #endif
                    DispatchQueue.main.async {
                        self.onAudioDataAvailable?(transcriptionData)
                    }
                } else if transcriptionData == nil {
                    #if DEBUG
                    DevLogger.shared.warning(
                        "Failed to convert global system output buffer to transcription data: frames=\(buffer.frameLength), format=\(RawAudioBufferListExtractor.describeAudioFormat(buffer.format))",
                        context: self.context
                    )
                    #endif
                }
                // An empty (non-nil) result is normal converter priming; skip silently.
            },
            invalidationHandler: { [weak self] _ in
                self?.handleInvalidation()
            }
        )

        #if DEBUG
        DevLogger.shared.info("Global system output recording started at \(fileURL.path)", context: context)
        #endif
    }

    func stop() {
        guard isRecording else { return }
        tap.invalidate()
        isRecording = false
        currentFile = nil
        startTime = nil
        deliveredBufferCount = 0
        DispatchQueue.main.async {
            self.audioLevel = 0.0
            self.previousLevel = 0.0
        }
    }

    private func handleInvalidation() {
        isRecording = false
        currentFile = nil
        deliveredBufferCount = 0
        DispatchQueue.main.async {
            self.audioLevel = 0.0
            self.previousLevel = 0.0
        }
    }

    private func updateMeter(from buffer: AVAudioPCMBuffer) {
        let level = calculateAudioLevel(buffer)
        let limitedLevel = previousLevel + min(maxAudioLevelJump, max(-maxAudioLevelJump, level - previousLevel))
        let smoothedLevel = (meterSmoothingFactor * limitedLevel) + ((1 - meterSmoothingFactor) * previousLevel)
        previousLevel = smoothedLevel
        meterUpdateCounter = (meterUpdateCounter + 1) % meterUpdateDivider
        if meterUpdateCounter == 0 {
            DispatchQueue.main.async {
                self.audioLevel = smoothedLevel
            }
        }
    }

    private func calculateAudioLevel(_ buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData else { return 0.0 }
        let channelCount = Int(buffer.format.channelCount)
        let frameLength = Int(buffer.frameLength)
        guard frameLength > 0, channelCount > 0 else { return 0.0 }

        var sumSquares: Float = 0.0
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

    private func logRawAudioBufferListStats(diagnostics: RawAudioBufferListExtractionDiagnostics) {
        rawDiagnosticBufferCount += 1
        guard rawDiagnosticBufferCount <= 5 || rawDiagnosticBufferCount % 250 == 0 else {
            return
        }

        #if DEBUG
        DevLogger.shared.info(
            "Raw global system output AudioBufferList \(rawDiagnosticBufferCount): \(diagnostics.summary)",
            context: context
        )
        #endif
    }

    private func handlePCMBufferCreationFailure(
        tapFormat: AVAudioFormat,
        inputData: UnsafePointer<AudioBufferList>
    ) {
        pcmBufferCreationFailureCount += 1

        #if DEBUG
        if pcmBufferCreationFailureCount == 1 || pcmBufferCreationFailureCount == 25 {
            DevLogger.shared.error(
                """
                Failed to create global system output PCM buffer.
                failure_count=\(pcmBufferCreationFailureCount)
                tap_format=\(RawAudioBufferListExtractor.describeAudioFormat(tapFormat))
                buffer_list=\(RawAudioBufferListExtractor.describeAudioBufferList(inputData))
                """,
                context: context
            )
        }
        #endif
    }

    private func resetPCMBufferCreationFailuresIfNeeded() {
        guard pcmBufferCreationFailureCount > 0 else { return }

        #if DEBUG
        DevLogger.shared.info(
            "Global system output PCM buffer creation recovered after \(pcmBufferCreationFailureCount) failure(s)",
            context: context
        )
        #endif

        pcmBufferCreationFailureCount = 0
    }

}
