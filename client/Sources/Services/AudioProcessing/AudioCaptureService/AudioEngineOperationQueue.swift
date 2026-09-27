@preconcurrency import AVFoundation
import Foundation

/// Serializes synchronous AVAudioEngine configuration away from the main actor.
final class AudioEngineOperationQueue: @unchecked Sendable {
    typealias BufferHandler = (AVAudioPCMBuffer, AVAudioFormat) -> Void

    struct Diagnostics: Sendable {
        let enginePointer: String
        let nodePointer: String
        let engineActive: Bool
        let nodeActive: Bool
        let nodeConnected: Bool
    }

    private final class InstallationInput: @unchecked Sendable {
        let engine: AVAudioEngine
        let targetFormat: AVAudioFormat
        let bufferHandler: BufferHandler

        init(
            engine: AVAudioEngine,
            targetFormat: AVAudioFormat,
            bufferHandler: @escaping BufferHandler
        ) {
            self.engine = engine
            self.targetFormat = targetFormat
            self.bufferHandler = bufferHandler
        }
    }

    private final class EngineInput: @unchecked Sendable {
        let engine: AVAudioEngine

        init(engine: AVAudioEngine) {
            self.engine = engine
        }
    }

    private let queue = DispatchQueue(
        label: "com.basil.audio-capture.engine-operations",
        qos: .userInitiated
    )

    func installAndPrepareTap(
        engine: AVAudioEngine,
        targetFormat: AVAudioFormat,
        maxRetries: Int = 3,
        retryDelayNanoseconds: UInt64 = 300_000_000,
        bufferHandler: @escaping BufferHandler
    ) async throws {
        let input = InstallationInput(
            engine: engine,
            targetFormat: targetFormat,
            bufferHandler: bufferHandler
        )

        for attempt in 0...maxRetries {
            do {
                try await installAndPrepareTapOnce(input)
                return
            } catch AudioCaptureError.noInputFormat where attempt < maxRetries {
                try await Task.sleep(nanoseconds: retryDelayNanoseconds)
            }
        }

        throw AudioCaptureError.noInputFormat
    }

    func start(_ engine: AVAudioEngine) async throws {
        let input = EngineInput(engine: engine)
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    if !input.engine.isRunning {
                        try input.engine.start()
                    }
                    continuation.resume()
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    func pauseAndRemoveTap(_ engine: AVAudioEngine) async {
        let input = EngineInput(engine: engine)
        await withCheckedContinuation { continuation in
            queue.async {
                if input.engine.isRunning {
                    input.engine.pause()
                }
                input.engine.inputNode.removeTap(onBus: 0)
                continuation.resume()
            }
        }
    }

    func runForTesting(_ operation: @escaping @Sendable () -> Void) async {
        await withCheckedContinuation { continuation in
            queue.async {
                operation()
                continuation.resume()
            }
        }
    }

    func diagnostics(for engine: AVAudioEngine) async -> Diagnostics {
        let input = EngineInput(engine: engine)
        return await withCheckedContinuation { continuation in
            queue.async {
                let node = input.engine.inputNode
                continuation.resume(
                    returning: Diagnostics(
                        enginePointer: String(
                            describing: Unmanaged.passUnretained(input.engine).toOpaque()
                        ),
                        nodePointer: String(
                            describing: Unmanaged.passUnretained(node).toOpaque()
                        ),
                        engineActive: input.engine.isRunning,
                        nodeActive: node.engine != nil,
                        nodeConnected: node.engine === input.engine
                    )
                )
            }
        }
    }

    private func installAndPrepareTapOnce(_ input: InstallationInput) async throws {
        try await withCheckedThrowingContinuation {
            (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                let inputNode = input.engine.inputNode
                inputNode.removeTap(onBus: 0)
                let sourceFormat = inputNode.inputFormat(forBus: 0)

                guard sourceFormat.sampleRate > 0, sourceFormat.channelCount > 0 else {
                    continuation.resume(throwing: AudioCaptureError.noInputFormat)
                    return
                }
                guard AVAudioConverter(
                    from: sourceFormat,
                    to: input.targetFormat
                ) != nil else {
                    continuation.resume(
                        throwing: AudioCaptureError.converterCreationFailed
                    )
                    return
                }

                inputNode.installTap(
                    onBus: 0,
                    bufferSize: 1024,
                    format: sourceFormat
                ) { buffer, _ in
                    input.bufferHandler(buffer, sourceFormat)
                }
                input.engine.prepare()
                continuation.resume()
            }
        }
    }
}
