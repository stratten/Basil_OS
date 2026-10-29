@preconcurrency import AVFoundation
import Foundation

/// Replays a session-owned audio fixture through the native capture-buffer boundary.
///
/// This source is available only in the isolated validation runtime. Normal Basil sessions
/// continue to use the selected hardware input device.
@MainActor
final class ValidationSyntheticAudioCaptureSource {
    static let fixtureRelativePath = "fixtures/audio/transcription-acceptance.wav"

    typealias BufferHandler = @MainActor (AVAudioPCMBuffer, AVAudioFormat) -> Void

    let fixtureURL: URL
    private(set) var playbackTask: Task<Void, Never>?
    private var playbackID: UUID?

    init(fixtureURL: URL) {
        self.fixtureURL = fixtureURL.standardizedFileURL
    }

    deinit {
        playbackTask?.cancel()
    }

    static func configuredForCurrentRuntime(
        fileManager: FileManager = .default
    ) -> ValidationSyntheticAudioCaptureSource? {
        guard let sessionRootURL = BasilRuntimeProfile.sessionRootURL else {
            return nil
        }
        let fixtureURL = sessionRootURL
            .appendingPathComponent(fixtureRelativePath)
            .standardizedFileURL
        guard fileManager.fileExists(atPath: fixtureURL.path) else {
            return nil
        }
        return ValidationSyntheticAudioCaptureSource(fixtureURL: fixtureURL)
    }

    func start(bufferHandler: @escaping BufferHandler) throws {
        stop()

        let audioFile = try AVAudioFile(forReading: fixtureURL)
        let sourceFormat = audioFile.processingFormat
        guard sourceFormat.sampleRate > 0, sourceFormat.channelCount > 0 else {
            throw AudioCaptureError.noInputFormat
        }

        let playbackID = UUID()
        self.playbackID = playbackID
        playbackTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if self.playbackID == playbackID {
                    self.playbackID = nil
                    self.playbackTask = nil
                }
            }

            do {
                while !Task.isCancelled,
                      self.playbackID == playbackID,
                      audioFile.framePosition < audioFile.length {
                    let remainingFrames = audioFile.length - audioFile.framePosition
                    let frameCount = AVAudioFrameCount(min(Int64(1024), remainingFrames))
                    guard frameCount > 0,
                          let buffer = AVAudioPCMBuffer(
                              pcmFormat: sourceFormat,
                              frameCapacity: frameCount
                          ) else {
                        return
                    }

                    try audioFile.read(into: buffer, frameCount: frameCount)
                    guard buffer.frameLength > 0 else { return }
                    bufferHandler(buffer, sourceFormat)

                    let frameDuration = Double(buffer.frameLength) / sourceFormat.sampleRate
                    try await Task.sleep(
                        nanoseconds: UInt64(frameDuration * 1_000_000_000)
                    )
                }
            } catch is CancellationError {
                return
            } catch {
                #if DEBUG
                DevLogger.shared.error(
                    "Validation synthetic audio playback failed: \(error)",
                    context: "AudioCaptureService"
                )
                #endif
            }
        }
    }

    func stop() {
        playbackID = nil
        playbackTask?.cancel()
        playbackTask = nil
    }
}
