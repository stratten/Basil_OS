import XCTest
import AVFoundation
@testable import BasilClient

final class AudioFormatTests: XCTestCase {
    var audioEngine: AVAudioEngine!
    var outputFormat: AVAudioFormat!
    
    override func setUp() {
        super.setUp()
        audioEngine = AVAudioEngine()
        // Target format: 16kHz mono PCM
        outputFormat = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)
    }
    
    override func tearDown() {
        audioEngine = nil
        outputFormat = nil
        super.tearDown()
    }
    
    func testAudioFormatConversion() throws {
        // Create a sample buffer with known values
        let sampleRate = 44100.0
        let inputFormat = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1)!
        let duration = 0.1 // 100ms
        let frameCount = AVAudioFrameCount(sampleRate * duration)
        
        guard let buffer = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: frameCount) else {
            XCTFail("Failed to create input buffer")
            return
        }
        
        // Fill buffer with a simple sine wave
        let frequency = 440.0 // A4 note
        for frame in 0..<Int(frameCount) {
            let value = sin(2.0 * .pi * frequency * Double(frame) / sampleRate)
            buffer.floatChannelData?[0][frame] = Float(value)
        }
        buffer.frameLength = frameCount
        
        // Create converter
        guard let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
            XCTFail("Failed to create converter")
            return
        }
        
        // Create output buffer
        let outputFrameCount = AVAudioFrameCount(Double(frameCount) * 16000.0 / sampleRate)
        guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: outputFrameCount) else {
            XCTFail("Failed to create output buffer")
            return
        }
        
        // Perform conversion
        var error: NSError?
        let status = converter.convert(to: outputBuffer, error: &error) { inNumPackets, outStatus in
            outStatus.pointee = .haveData
            return buffer
        }
        
        // Verify conversion
        XCTAssertNil(error, "Conversion error: \(String(describing: error))")
        XCTAssertEqual(status, .haveData, "Conversion failed")
        XCTAssertGreaterThan(outputBuffer.frameLength, 0, "No frames in output buffer")
        
        // Convert to Data
        let data = outputBuffer.toData()
        XCTAssertNotNil(data, "Failed to convert buffer to data")
        XCTAssertGreaterThan(data?.count ?? 0, 0, "Empty data")
    }
    
    func testStreamingBufferConversion() throws {
        // Test converting smaller chunks as would happen in streaming
        let sampleRate = 44100.0
        let inputFormat = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1)!
        let chunkDuration = 0.02 // 20ms chunks
        let frameCount = AVAudioFrameCount(sampleRate * chunkDuration)
        
        guard let buffer = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: frameCount) else {
            XCTFail("Failed to create input buffer")
            return
        }
        
        // Fill buffer with simple values
        for frame in 0..<Int(frameCount) {
            buffer.floatChannelData?[0][frame] = Float(frame % 100) / 100.0
        }
        buffer.frameLength = frameCount
        
        // Create converter
        guard let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
            XCTFail("Failed to create converter")
            return
        }
        
        // Create output buffer
        let outputFrameCount = AVAudioFrameCount(Double(frameCount) * 16000.0 / sampleRate)
        guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: outputFrameCount) else {
            XCTFail("Failed to create output buffer")
            return
        }
        
        // Test multiple chunks
        for _ in 0..<5 {
            var error: NSError?
            let status = converter.convert(to: outputBuffer, error: &error) { inNumPackets, outStatus in
                outStatus.pointee = .haveData
                return buffer
            }
            
            XCTAssertNil(error, "Conversion error: \(String(describing: error))")
            XCTAssertEqual(status, .haveData, "Conversion failed")
            
            let data = outputBuffer.toData()
            XCTAssertNotNil(data, "Failed to convert buffer to data")
            XCTAssertGreaterThan(data?.count ?? 0, 0, "Empty data")
        }
    }
} 