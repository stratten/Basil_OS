@preconcurrency import AVFoundation
import Foundation

extension AudioCaptureService {
    func processAudioBuffer(_ buffer: AVAudioPCMBuffer, sourceFormat: AVAudioFormat) {
        // Moved level calculation outside of #if DEBUG
        let level = calculateAudioLevel(from: buffer) 
        #if DEBUG
            if level > 0 {
                DevLogger.shared.info("Nonzero audio level detected: \(level)", context: "AudioCaptureService")
            }
        #endif
        guard isRecording,
              let format = audioFormat else { return }
        
        // Update audio level meter using source buffer
        let currentTime = Date().timeIntervalSince1970
        if currentTime - lastAudioLevelUpdate >= audioLevelUpdateInterval {
            DispatchQueue.main.async {
                self.audioLevel = level
            }
            lastAudioLevelUpdate = currentTime
        }
        
        // Create converter if needed
        guard let converter = AVAudioConverter(from: sourceFormat, to: format) else {
            print("Failed to create audio converter")
            return
        }
        
        // Calculate output buffer size based on sample rates
        let sourceRate = sourceFormat.sampleRate
        let targetRate = format.sampleRate
        let ratio = sourceRate / targetRate
        let frameCount = AVAudioFrameCount(Double(buffer.frameLength) / ratio)
        
        // Verify reasonable conversion ratio
        guard ratio > 0.1 && ratio < 10 else {
            print("Unreasonable sample rate conversion ratio: \(ratio)")
            print("Source rate: \(sourceRate) Hz")
            print("Target rate: \(targetRate) Hz")
            return
        }
        
        guard let outputBuffer = AVAudioPCMBuffer(
            pcmFormat: format,
            frameCapacity: frameCount
        ) else {
            print("Failed to create output buffer")
            return
        }
        
        outputBuffer.frameLength = frameCount
        
        var error: NSError?
        let status = converter.convert(
            to: outputBuffer,
            error: &error
        ) { inNumPackets, outStatus in
            outStatus.pointee = .haveData
            return buffer
        }
        
        if let error = error {
            print("Conversion error: \(error)")
            return
        }
        
        guard status != .error,
              let channelData = outputBuffer.floatChannelData else {
            print("Invalid conversion status or channel data")
            return
        }
        
        // Verify output format
        guard outputBuffer.format.sampleRate == 16000,
              outputBuffer.format.channelCount == 1 else {
            print("Output buffer has incorrect format:")
            print("- Sample rate: \(outputBuffer.format.sampleRate) Hz")
            print("- Channels: \(outputBuffer.format.channelCount)")
            return
        }
        
        // Append the converted PCM data
        let frameLength = Int(outputBuffer.frameLength)
        let bytesPerFrame = MemoryLayout<Float>.size
        let data = Data(
            bytes: channelData[0],
            count: frameLength * bytesPerFrame
        )
        
        recordingData.append(data)
        Task { @MainActor [weak self] in
            self?.signalFirstCapturedBuffer()
        }

        #if DEBUG
        if recordingData.count % 32000 == 0 && recordingData.count > 0 { // Log every ~2 seconds at 16kHz
            DevLogger.shared.info("[AUDIO CAPTURE] 📊 Recording data accumulated: \(recordingData.count) bytes (\(String(format: "%.1f", Double(recordingData.count) / 64000.0))s)", context: "AudioCaptureService")
        }
        #endif
    }
    
    func calculateAudioLevel(from buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData?[0],
              buffer.frameLength > 0 else { return 0.0 }
        
        // Calculate RMS (Root Mean Square) of the audio samples
        var sum = Float(0.0)
        for i in 0..<Int(buffer.frameLength) {
            let sample = channelData[i]
            sum += sample * sample
        }
        let rms = sqrt(sum / Float(buffer.frameLength))
        
        // Convert to decibels and normalize
        let db = 20 * log10(rms)
        // Normalize to 0-1 range, assuming typical audio levels
        // -50 dB is near silence, 0 dB is maximum
        let normalized = (db + 50) / 50
        return max(0, min(1, normalized))
    }
    
    // MARK: - Context Information Methods
    func setContextInfo(appName: String?, windowTitle: String?, taskCategory: String?) {
        contextInfo["app_name"] = appName
        contextInfo["window_title"] = windowTitle
        contextInfo["task_category"] = taskCategory
        
        #if DEBUG
            DevLogger.shared.info("Context info set - App: \(appName ?? "nil"), Window: \(windowTitle ?? "nil"), Task: \(taskCategory ?? "nil")", context: "AudioCapture")
        #endif
    }
    
    func clearContextInfo() {
        contextInfo["app_name"] = nil
        contextInfo["window_title"] = nil
        contextInfo["task_category"] = nil
        
        #if DEBUG
            DevLogger.shared.info("Context info cleared", context: "AudioCapture")
        #endif
    }
}

