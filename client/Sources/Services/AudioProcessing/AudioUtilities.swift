import Foundation
import AVFoundation
import AudioToolbox

extension AVAudioPCMBuffer {
    func toData() -> Data? {
        guard let channelData = self.floatChannelData else { return nil }
        let channelCount = Int(self.format.channelCount)
        let frameLength = Int(self.frameLength)
        let data = NSMutableData()
        
        for channel in 0..<channelCount {
            let samples = channelData[channel]
            data.append(samples, length: frameLength * MemoryLayout<Float>.size)
        }
        
        return data as Data
    }
    
    /// Returns a copy of this buffer with the same float samples, channel count,
    /// and frame length but a corrected sample rate. Used to re-stamp a buffer
    /// whose declared rate is wrong (see AudioInputRateEstimator) before
    /// resampling, without disturbing the original buffer used for file writes.
    ///
    /// Only valid for float32 buffers; returns nil otherwise so the caller can
    /// fall back to the original buffer.
    func relabeled(sampleRate: Double) -> AVAudioPCMBuffer? {
        guard sampleRate > 0 else { return nil }
        guard sampleRate != format.sampleRate else { return self }
        guard let sourceChannels = floatChannelData else { return nil }
        guard let newFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: format.channelCount,
            interleaved: false
        ),
        let newBuffer = AVAudioPCMBuffer(pcmFormat: newFormat, frameCapacity: max(frameLength, 1)) else {
            return nil
        }

        newBuffer.frameLength = frameLength
        guard let destinationChannels = newBuffer.floatChannelData else { return nil }

        let channelCount = Int(format.channelCount)
        let frames = Int(frameLength)
        for channel in 0..<channelCount {
            destinationChannels[channel].update(from: sourceChannels[channel], count: frames)
        }
        return newBuffer
    }

    static func fromData(_ data: Data, format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let channelCount = Int(format.channelCount)
        let bytesPerFrame = channelCount * MemoryLayout<Float>.size
        let frameCount = UInt32(data.count / bytesPerFrame)
        
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else {
            return nil
        }
        
        buffer.frameLength = frameCount
        
        // Copy data to buffer
        data.withUnsafeBytes { rawBufferPointer in
            guard let floatBuffer = rawBufferPointer.bindMemory(to: Float.self).baseAddress else {
                return
            }
            
            for channel in 0..<channelCount {
                let dst = buffer.floatChannelData?[channel]
                for frame in 0..<Int(frameCount) {
                    dst?[frame] = floatBuffer[frame * channelCount + channel]
                }
            }
        }
        
        return buffer
    }
}

struct RawAudioBufferListExtractionDiagnostics {
    let rms: Double
    let peak: Double
    let sampleCount: Int
    let nonZeroPercent: Double
    let selectedBufferIndex: Int?
    let formatDescription: String
    let bufferListDescription: String

    var summary: String {
        let selectedBufferText = selectedBufferIndex.map { "\($0)" } ?? "none"
        return "rms=\(rms), peak=\(peak), samples=\(sampleCount), nonzero_gt_1e-5=\(String(format: "%.2f", nonZeroPercent))%, selected_buffer=\(selectedBufferText), format=\(formatDescription), buffer_list=\(bufferListDescription)"
    }
}

struct RawAudioBufferListExtractionResult {
    let pcmBuffer: AVAudioPCMBuffer
    let diagnostics: RawAudioBufferListExtractionDiagnostics
}

enum RawAudioBufferListExtractor {
    static func extractPCMBuffer(
        format: AVAudioFormat,
        inputData: UnsafePointer<AudioBufferList>
    ) -> RawAudioBufferListExtractionResult? {
        let candidateBuffers = makeCandidateBuffers(format: format, inputData: inputData)
        let allStats = candidateBuffers.reduce(AudioSampleStats.empty) { partial, candidate in
            partial.combined(with: candidate.stats)
        }

        let isLouder: (AudioBufferCandidate, AudioBufferCandidate) -> Bool = { lhs, rhs in
            if lhs.stats.rms != rhs.stats.rms {
                return lhs.stats.rms < rhs.stats.rms
            }
            if lhs.stats.nonZeroCount != rhs.stats.nonZeroCount {
                return lhs.stats.nonZeroCount < rhs.stats.nonZeroCount
            }
            return lhs.byteCount < rhs.byteCount
        }

        // Prefer the buffer whose channel count matches the declared tap OUTPUT
        // format. A combo input/output device (e.g. a headset that is both mic
        // and speakers) surfaces its microphone as an EXTRA buffer in the tap's
        // IO list — typically mono while the output tap stream is stereo. Picking
        // purely by loudness then grabbed that mic buffer whenever the user spoke
        // with nothing playing, so the "system audio" stream transcribed the
        // microphone and the same speech showed up under both sources. Restrict
        // selection to format-matching buffers first; only fall back to the full
        // set (loudest) when no buffer matches the output channel count.
        let formatChannelCount = Int(format.channelCount)
        let formatMatchedBuffers = candidateBuffers.filter { $0.sourceChannelCount == formatChannelCount }
        let selectionPool = formatMatchedBuffers.isEmpty ? candidateBuffers : formatMatchedBuffers
        let selectedCandidate = selectionPool.max(by: isLouder)

        guard let selectedCandidate,
              let pcmBuffer = makePCMBuffer(from: selectedCandidate, format: format) else {
            return nil
        }

        return RawAudioBufferListExtractionResult(
            pcmBuffer: pcmBuffer,
            diagnostics: makeDiagnostics(
                format: format,
                inputData: inputData,
                selectedBufferIndex: selectedCandidate.index,
                stats: allStats
            )
        )
    }

    static func makeDiagnostics(
        format: AVAudioFormat,
        inputData: UnsafePointer<AudioBufferList>,
        selectedBufferIndex: Int? = nil
    ) -> RawAudioBufferListExtractionDiagnostics {
        let stats = makeCandidateBuffers(format: format, inputData: inputData).reduce(AudioSampleStats.empty) { partial, candidate in
            partial.combined(with: candidate.stats)
        }

        return makeDiagnostics(
            format: format,
            inputData: inputData,
            selectedBufferIndex: selectedBufferIndex,
            stats: stats
        )
    }

    static func describeAudioFormat(_ format: AVAudioFormat) -> String {
        let description = format.streamDescription.pointee
        return "sampleRate=\(format.sampleRate), channels=\(format.channelCount), commonFormat=\(format.commonFormat.rawValue), interleaved=\(format.isInterleaved), bytesPerFrame=\(description.mBytesPerFrame), framesPerPacket=\(description.mFramesPerPacket), formatFlags=\(description.mFormatFlags)"
    }

    static func describeAudioBufferList(_ inputData: UnsafePointer<AudioBufferList>) -> String {
        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inputData))
        let descriptions = buffers.enumerated().map { index, buffer in
            "#\(index)(channels=\(buffer.mNumberChannels), byteSize=\(buffer.mDataByteSize), hasData=\(buffer.mData != nil))"
        }
        return "count=\(buffers.count) [\(descriptions.joined(separator: ", "))]"
    }

    private static func makeDiagnostics(
        format: AVAudioFormat,
        inputData: UnsafePointer<AudioBufferList>,
        selectedBufferIndex: Int?,
        stats: AudioSampleStats
    ) -> RawAudioBufferListExtractionDiagnostics {
        RawAudioBufferListExtractionDiagnostics(
            rms: stats.rms,
            peak: stats.peak,
            sampleCount: stats.sampleCount,
            nonZeroPercent: stats.nonZeroPercent,
            selectedBufferIndex: selectedBufferIndex,
            formatDescription: describeAudioFormat(format),
            bufferListDescription: describeAudioBufferList(inputData)
        )
    }

    private static func makeCandidateBuffers(
        format: AVAudioFormat,
        inputData: UnsafePointer<AudioBufferList>
    ) -> [AudioBufferCandidate] {
        let streamDescription = format.streamDescription.pointee
        let sampleByteCount = Int(streamDescription.mBitsPerChannel / 8)
        guard sampleByteCount > 0 else { return [] }

        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inputData))
        var candidates: [AudioBufferCandidate] = []

        for (index, buffer) in buffers.enumerated() {
            guard let data = buffer.mData else { continue }
            let byteCount = Int(buffer.mDataByteSize)
            guard byteCount >= sampleByteCount else { continue }

            let sourceChannelCount = max(1, Int(buffer.mNumberChannels))
            let frameCount = byteCount / (sampleByteCount * sourceChannelCount)
            guard frameCount > 0 else { continue }

            let stats = calculateStats(
                data: data,
                byteCount: byteCount,
                streamDescription: streamDescription
            )

            candidates.append(
                AudioBufferCandidate(
                    index: index,
                    data: data,
                    byteCount: byteCount,
                    sourceChannelCount: sourceChannelCount,
                    frameCount: frameCount,
                    streamDescription: streamDescription,
                    stats: stats
                )
            )
        }

        return candidates
    }

    private static func makePCMBuffer(
        from candidate: AudioBufferCandidate,
        format: AVAudioFormat
    ) -> AVAudioPCMBuffer? {
        let outputChannelCount = max(1, Int(format.channelCount))
        guard let outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: format.sampleRate,
            channels: AVAudioChannelCount(outputChannelCount),
            interleaved: false
        ),
        let outputBuffer = AVAudioPCMBuffer(
            pcmFormat: outputFormat,
            frameCapacity: AVAudioFrameCount(candidate.frameCount)
        ),
        let outputChannelData = outputBuffer.floatChannelData else {
            return nil
        }

        outputBuffer.frameLength = AVAudioFrameCount(candidate.frameCount)

        for outputChannel in 0..<outputChannelCount {
            let sourceChannel = min(outputChannel, candidate.sourceChannelCount - 1)
            let destination = outputChannelData[outputChannel]

            for frame in 0..<candidate.frameCount {
                destination[frame] = sampleValue(
                    candidate: candidate,
                    frame: frame,
                    channel: sourceChannel
                )
            }
        }

        return outputBuffer
    }

    private static func calculateStats(
        data: UnsafeMutableRawPointer,
        byteCount: Int,
        streamDescription: AudioStreamBasicDescription
    ) -> AudioSampleStats {
        let sampleByteCount = Int(streamDescription.mBitsPerChannel / 8)
        guard sampleByteCount > 0 else { return .empty }

        let sampleCount = byteCount / sampleByteCount
        var stats = AudioSampleStats.empty

        for sampleIndex in 0..<sampleCount {
            let value = Double(sampleValue(
                data: data,
                sampleIndex: sampleIndex,
                streamDescription: streamDescription
            ))
            guard value.isFinite else { continue }
            stats = stats.addingSample(value)
        }

        return stats
    }

    private static func sampleValue(
        candidate: AudioBufferCandidate,
        frame: Int,
        channel: Int
    ) -> Float {
        let sampleIndex = (frame * candidate.sourceChannelCount) + channel
        return sampleValue(
            data: candidate.data,
            sampleIndex: sampleIndex,
            streamDescription: candidate.streamDescription
        )
    }

    private static func sampleValue(
        data: UnsafeMutableRawPointer,
        sampleIndex: Int,
        streamDescription: AudioStreamBasicDescription
    ) -> Float {
        let sampleByteCount = Int(streamDescription.mBitsPerChannel / 8)
        let isFloat = (streamDescription.mFormatFlags & kAudioFormatFlagIsFloat) != 0
        let isSignedInteger = (streamDescription.mFormatFlags & kAudioFormatFlagIsSignedInteger) != 0

        if isFloat && sampleByteCount == MemoryLayout<Float32>.size {
            return data.bindMemory(to: Float32.self, capacity: sampleIndex + 1)[sampleIndex]
        }

        if isSignedInteger && sampleByteCount == MemoryLayout<Int16>.size {
            let value = data.bindMemory(to: Int16.self, capacity: sampleIndex + 1)[sampleIndex]
            return Float(value) / Float(Int16.max)
        }

        if isSignedInteger && sampleByteCount == MemoryLayout<Int32>.size {
            let value = data.bindMemory(to: Int32.self, capacity: sampleIndex + 1)[sampleIndex]
            return Float(value) / Float(Int32.max)
        }

        return 0.0
    }

    private struct AudioBufferCandidate {
        let index: Int
        let data: UnsafeMutableRawPointer
        let byteCount: Int
        let sourceChannelCount: Int
        let frameCount: Int
        let streamDescription: AudioStreamBasicDescription
        let stats: AudioSampleStats
    }

    private struct AudioSampleStats {
        let sampleCount: Int
        let sumSquares: Double
        let peak: Double
        let nonZeroCount: Int

        static let empty = AudioSampleStats(
            sampleCount: 0,
            sumSquares: 0,
            peak: 0,
            nonZeroCount: 0
        )

        var rms: Double {
            sampleCount > 0 ? sqrt(sumSquares / Double(sampleCount)) : 0.0
        }

        var nonZeroPercent: Double {
            sampleCount > 0 ? (Double(nonZeroCount) / Double(sampleCount)) * 100.0 : 0.0
        }

        func addingSample(_ value: Double) -> AudioSampleStats {
            AudioSampleStats(
                sampleCount: sampleCount + 1,
                sumSquares: sumSquares + (value * value),
                peak: max(peak, abs(value)),
                nonZeroCount: nonZeroCount + (abs(value) > 0.00001 ? 1 : 0)
            )
        }

        func combined(with other: AudioSampleStats) -> AudioSampleStats {
            AudioSampleStats(
                sampleCount: sampleCount + other.sampleCount,
                sumSquares: sumSquares + other.sumSquares,
                peak: max(peak, other.peak),
                nonZeroCount: nonZeroCount + other.nonZeroCount
            )
        }
    }
}