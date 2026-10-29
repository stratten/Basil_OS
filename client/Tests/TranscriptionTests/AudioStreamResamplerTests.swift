import XCTest
import AVFoundation
@testable import BasilClient

/// Proves the streaming resampler preserves audio duration across many small
/// buffers (the fix for the system-audio "chipmunk" artifact) and documents the
/// per-buffer-converter defect it replaces.
final class AudioStreamResamplerTests: XCTestCase {

    private let outputRate = 16000.0

    // MARK: - Helpers

    /// Builds a float32 non-interleaved sine buffer. `startFrame` keeps phase
    /// continuous when a longer signal is split into consecutive chunks.
    private func makeSineBuffer(
        sampleRate: Double,
        channels: AVAudioChannelCount,
        frameCount: AVAudioFrameCount,
        frequency: Double = 440.0,
        startFrame: Int = 0
    ) -> AVAudioPCMBuffer {
        let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: channels,
            interleaved: false
        )!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: max(frameCount, 1))!
        buffer.frameLength = frameCount
        if let channelData = buffer.floatChannelData {
            for channel in 0..<Int(channels) {
                for frame in 0..<Int(frameCount) {
                    let t = Double(startFrame + frame) / sampleRate
                    channelData[channel][frame] = Float(sin(2.0 * .pi * frequency * t))
                }
            }
        }
        return buffer
    }

    private func frameCount(of data: Data) -> Int {
        data.count / MemoryLayout<Float>.size
    }

    private func samples(of data: Data) -> [Float] {
        data.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
    }

    /// Estimates the dominant frequency of a mono signal via zero-crossing rate.
    /// A pitch (chipmunk) shift shows up directly as an inflated frequency.
    private func estimateFrequency(_ samples: [Float], sampleRate: Double) -> Double {
        guard samples.count > 1 else { return 0 }
        let threshold: Float = 0.05 // ignore near-zero jitter
        var crossings = 0
        var lastSign = 0
        for sample in samples {
            let sign: Int
            if sample > threshold { sign = 1 } else if sample < -threshold { sign = -1 } else { sign = lastSign }
            if lastSign != 0 && sign != 0 && sign != lastSign { crossings += 1 }
            if sign != 0 { lastSign = sign }
        }
        let seconds = Double(samples.count) / sampleRate
        return (Double(crossings) / 2.0) / seconds
    }

    /// Concatenated mono output when each chunk is converted with a brand-new
    /// converter (a faithful replica of the original toTranscriptionData()).
    private func perBufferConvertedSamples(
        chunks: [AVAudioPCMBuffer]
    ) -> [Float] {
        let outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: outputRate,
            channels: 1,
            interleaved: false
        )!
        var result: [Float] = []
        for buffer in chunks {
            guard let converter = AVAudioConverter(from: buffer.format, to: outputFormat) else { continue }
            converter.sampleRateConverterQuality = .max
            let outFrames = AVAudioFrameCount(Double(buffer.frameLength) * (outputRate / buffer.format.sampleRate))
            guard let output = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: max(outFrames, 1)) else { continue }
            var error: NSError?
            _ = converter.convert(to: output, error: &error) { _, outStatus in
                outStatus.pointee = .haveData
                return buffer
            }
            if let channel = output.floatChannelData {
                result.append(contentsOf: UnsafeBufferPointer(start: channel[0], count: Int(output.frameLength)))
            }
        }
        return result
    }

    private func streamedSamples(
        chunks: [AVAudioPCMBuffer],
        resampler: AudioStreamResampler
    ) -> [Float] {
        var result: [Float] = []
        for buffer in chunks {
            if let data = resampler.resampledData(from: buffer) {
                result.append(contentsOf: samples(of: data))
            }
        }
        return result
    }

    private func streamedFrames(
        chunks: [AVAudioPCMBuffer],
        resampler: AudioStreamResampler
    ) -> Int {
        var total = 0
        for buffer in chunks {
            if let data = resampler.resampledData(from: buffer) {
                total += frameCount(of: data)
            } else {
                XCTFail("Resampler returned nil for a valid buffer")
            }
        }
        return total
    }

    // MARK: - Tests

    func testStreamingEqualsBatchDurationPreserved() {
        // 1 second of 48 kHz audio split into 100 x 10 ms chunks.
        let inputRate = 48000.0
        let chunkFrames: AVAudioFrameCount = 480
        let chunkCount = 100
        var chunks: [AVAudioPCMBuffer] = []
        for index in 0..<chunkCount {
            chunks.append(makeSineBuffer(
                sampleRate: inputRate,
                channels: 1,
                frameCount: chunkFrames,
                startFrame: index * Int(chunkFrames)
            ))
        }

        let streamTotal = streamedFrames(chunks: chunks, resampler: AudioStreamResampler())

        // Batch: the entire signal converted as one buffer through one resampler.
        let batchBuffer = makeSineBuffer(
            sampleRate: inputRate,
            channels: 1,
            frameCount: chunkFrames * AVAudioFrameCount(chunkCount)
        )
        let batchTotal = frameCount(of: AudioStreamResampler().resampledData(from: batchBuffer) ?? Data())

        let ideal = Double(chunkCount) * Double(chunkFrames) * (outputRate / inputRate) // 16000
        XCTAssertEqual(Double(streamTotal), ideal, accuracy: ideal * 0.01,
                       "Streamed output duration drifted from real time (chipmunk regression)")
        XCTAssertEqual(Double(streamTotal), Double(batchTotal), accuracy: ideal * 0.01,
                       "Chunked streaming should match batch conversion frame count")
    }

    func testResamplerPreservesPitchOnStereoInput() {
        // Mirrors the real system tap: stereo 48 kHz delivered in 10 ms chunks.
        let inputRate = 48000.0
        let chunkFrames: AVAudioFrameCount = 480
        let chunkCount = 100
        let tone = 1000.0
        var chunks: [AVAudioPCMBuffer] = []
        for index in 0..<chunkCount {
            chunks.append(makeSineBuffer(
                sampleRate: inputRate,
                channels: 2,
                frameCount: chunkFrames,
                frequency: tone,
                startFrame: index * Int(chunkFrames)
            ))
        }

        let streamed = streamedSamples(chunks: chunks, resampler: AudioStreamResampler())
        let perBuffer = perBufferConvertedSamples(chunks: chunks)
        let streamFreq = estimateFrequency(streamed, sampleRate: outputRate)
        let perBufferFreq = estimateFrequency(perBuffer, sampleRate: outputRate)

        // The fixed path must reproduce the original pitch (no chipmunk).
        XCTAssertEqual(streamFreq, tone, accuracy: tone * 0.05,
                       "Persistent resampler must preserve pitch; streamFreq=\(streamFreq) Hz perBufferFreq=\(perBufferFreq) Hz for a \(tone) Hz tone")
        // The persistent resampler must be at least as faithful as the per-buffer approach.
        XCTAssertLessThanOrEqual(abs(streamFreq - tone), abs(perBufferFreq - tone) + 1.0,
                                 "Persistent resampler deviated more than per-buffer; streamFreq=\(streamFreq) perBufferFreq=\(perBufferFreq)")
    }

    func testInputFormatChangeMidStream() {
        let resampler = AudioStreamResampler()

        // First segment at 48 kHz.
        for index in 0..<100 {
            let buffer = makeSineBuffer(sampleRate: 48000.0, channels: 1, frameCount: 480, startFrame: index * 480)
            XCTAssertNotNil(resampler.resampledData(from: buffer))
        }

        // Second segment at 44.1 kHz through the SAME instance (device switched).
        let secondRate = 44100.0
        let secondChunkFrames: AVAudioFrameCount = 441
        let secondChunkCount = 100
        var secondTotal = 0
        for index in 0..<secondChunkCount {
            let buffer = makeSineBuffer(
                sampleRate: secondRate,
                channels: 1,
                frameCount: secondChunkFrames,
                startFrame: index * Int(secondChunkFrames)
            )
            guard let data = resampler.resampledData(from: buffer) else {
                XCTFail("Resampler returned nil after format change")
                return
            }
            secondTotal += frameCount(of: data)
        }

        let ideal = Double(secondChunkCount) * Double(secondChunkFrames) * (outputRate / secondRate)
        XCTAssertEqual(Double(secondTotal), ideal, accuracy: ideal * 0.01,
                       "Output after a mid-stream sample-rate change should track real time")
    }

    func testStereoDownmixToMono() {
        let inputRate = 48000.0
        let chunkFrames: AVAudioFrameCount = 480
        let chunkCount = 100
        let resampler = AudioStreamResampler()
        var total = 0
        for index in 0..<chunkCount {
            let buffer = makeSineBuffer(
                sampleRate: inputRate,
                channels: 2,
                frameCount: chunkFrames,
                startFrame: index * Int(chunkFrames)
            )
            guard let data = resampler.resampledData(from: buffer) else {
                XCTFail("Resampler returned nil for stereo input")
                return
            }
            total += frameCount(of: data)
        }

        let ideal = Double(chunkCount) * Double(chunkFrames) * (outputRate / inputRate)
        XCTAssertEqual(Double(total), ideal, accuracy: ideal * 0.01,
                       "Stereo input should downmix to mono and preserve duration")
    }

    func testFastPathPassthrough() {
        let frames: AVAudioFrameCount = 1600
        let buffer = makeSineBuffer(sampleRate: 16000.0, channels: 1, frameCount: frames)
        let data = AudioStreamResampler().resampledData(from: buffer)
        XCTAssertEqual(data?.count, Int(frames) * MemoryLayout<Float>.size,
                       "A 16 kHz mono buffer should pass through untouched")
    }

    func testEmptyBufferReturnsEmptyNotNil() {
        let buffer = makeSineBuffer(sampleRate: 48000.0, channels: 1, frameCount: 0)
        let data = AudioStreamResampler().resampledData(from: buffer)
        XCTAssertNotNil(data, "A zero-frame buffer is not a failure")
        XCTAssertTrue(data?.isEmpty ?? false, "A zero-frame buffer should yield empty data")
    }
}
