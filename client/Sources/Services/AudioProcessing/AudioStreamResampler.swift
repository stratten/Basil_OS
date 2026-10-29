import AVFoundation
import Foundation

/// Streaming PCM resampler to a fixed transcription format (default 16 kHz mono float32).
///
/// Reuse ONE instance for an entire audio stream so the underlying
/// AVAudioConverter keeps its resampling filter state between callbacks.
/// Creating a converter per buffer discards the resampler's delay-line tail
/// every callback, time-compressing the output (the "chipmunk" artifact);
/// see AudioStreamResamplerTests.
///
/// Not thread-safe: call `resampledData(from:)` from a single serial context.
final class AudioStreamResampler {
    private let outputFormat: AVAudioFormat
    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?

    init(sampleRate: Double = 16000, channels: AVAudioChannelCount = 1) {
        // 16 kHz mono float32 non-interleaved is always a valid format.
        self.outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: channels,
            interleaved: false
        )!
    }

    /// Converts one buffer to the output format, preserving converter state.
    /// Returns channel-0 sample bytes (possibly empty during converter priming),
    /// or nil on a hard conversion failure.
    func resampledData(from buffer: AVAudioPCMBuffer) -> Data? {
        guard buffer.frameLength > 0 else { return Data() }

        let sourceFormat = buffer.format

        if formatsMatch(sourceFormat, outputFormat), let channel = buffer.floatChannelData {
            return Data(bytes: channel[0], count: Int(buffer.frameLength) * MemoryLayout<Float>.size)
        }

        if converter == nil || !(inputFormat.map { formatsMatch($0, sourceFormat) } ?? false) {
            guard let newConverter = AVAudioConverter(from: sourceFormat, to: outputFormat) else { return nil }
            newConverter.sampleRateConverterQuality = .max
            converter = newConverter
            inputFormat = sourceFormat
        }
        guard let converter else { return nil }

        let ratio = outputFormat.sampleRate / sourceFormat.sampleRate
        let capacity = AVAudioFrameCount((Double(buffer.frameLength) * ratio).rounded(.up)) + 32
        guard capacity > 0,
              let outputBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity) else {
            return nil
        }

        var consumed = false
        var conversionError: NSError?
        let status = converter.convert(to: outputBuffer, error: &conversionError) { _, outStatus in
            if consumed {
                outStatus.pointee = .noDataNow
                return nil
            }
            consumed = true
            outStatus.pointee = .haveData
            return buffer
        }

        if status == .error || conversionError != nil { return nil }
        guard let channel = outputBuffer.floatChannelData else { return nil }
        return Data(bytes: channel[0], count: Int(outputBuffer.frameLength) * MemoryLayout<Float>.size)
    }

    private func formatsMatch(_ a: AVAudioFormat, _ b: AVAudioFormat) -> Bool {
        a.sampleRate == b.sampleRate
            && a.channelCount == b.channelCount
            && a.commonFormat == b.commonFormat
            && a.isInterleaved == b.isInterleaved
    }
}
