import XCTest
import AVFoundation
@testable import BasilClient

/// Proves the throughput-based rate estimator: it holds the declared rate under
/// matching throughput (the regression guard for normal calls), converges to the
/// true rate when throughput halves (the AirPods profile-switch case), rejects
/// noise, and does not flap. Also covers buffer relabeling used to apply the
/// corrected rate.
final class AudioInputRateEstimatorTests: XCTestCase {

    private var clock: UInt64 = 0

    private func makeEstimator() -> AudioInputRateEstimator {
        clock = 0
        return AudioInputRateEstimator(
            windowSeconds: 1.0,
            snapTolerance: 0.12,
            confirmCount: 2,
            now: { [weak self] in self?.clock ?? 0 }
        )
    }

    /// Drives one complete measurement window delivering `frames` frames over
    /// `seconds` of (simulated) wall time.
    private func deliverWindow(_ estimator: AudioInputRateEstimator, frames: Int, seconds: Double = 1.0) {
        estimator.observe(frameCount: 0) // start/continue the current window
        clock += UInt64(seconds * 1_000_000_000.0)
        estimator.observe(frameCount: AVAudioFrameCount(frames)) // cross the window boundary
    }

    // MARK: - Estimator behavior

    func testStableRateNeverSwitches() {
        let estimator = makeEstimator()
        estimator.reset(declaredSampleRate: 48000)
        for _ in 0..<10 {
            deliverWindow(estimator, frames: 48000)
            XCTAssertEqual(estimator.estimatedSampleRate, 48000,
                           "Matching throughput must never move the estimate off the declared rate")
        }
    }

    func testConvergesToHalfRateThenReverts() {
        let estimator = makeEstimator()
        estimator.reset(declaredSampleRate: 48000)

        deliverWindow(estimator, frames: 48000)
        XCTAssertEqual(estimator.estimatedSampleRate, 48000)

        // Half-rate throughput (the chipmunk condition): one window is not enough.
        deliverWindow(estimator, frames: 24000)
        XCTAssertEqual(estimator.estimatedSampleRate, 48000, "Should require confirmation before switching")

        deliverWindow(estimator, frames: 24000)
        XCTAssertEqual(estimator.estimatedSampleRate, 24000, "Two confirming windows should adopt the true rate")

        // Throughput returns to full rate; it should revert after confirmation.
        deliverWindow(estimator, frames: 48000)
        XCTAssertEqual(estimator.estimatedSampleRate, 24000)
        deliverWindow(estimator, frames: 48000)
        XCTAssertEqual(estimator.estimatedSampleRate, 48000)
    }

    func testNoisyMeasurementKeepsCurrentRate() {
        let estimator = makeEstimator()
        estimator.reset(declaredSampleRate: 48000)
        // 37000 is >12% from every standard rate -> unreliable -> keep current.
        deliverWindow(estimator, frames: 37000)
        XCTAssertEqual(estimator.estimatedSampleRate, 48000)
        deliverWindow(estimator, frames: 37000)
        XCTAssertEqual(estimator.estimatedSampleRate, 48000)
    }

    func testFlappingDoesNotSwitch() {
        let estimator = makeEstimator()
        estimator.reset(declaredSampleRate: 48000)
        // Alternating windows never give two consecutive confirmations.
        for _ in 0..<6 {
            deliverWindow(estimator, frames: 24000)
            deliverWindow(estimator, frames: 48000)
        }
        XCTAssertEqual(estimator.estimatedSampleRate, 48000)
    }

    func testSnapNearestWithinTolerance() {
        XCTAssertEqual(AudioInputRateEstimator.snap(24010, tolerance: 0.12), 24000)
        XCTAssertEqual(AudioInputRateEstimator.snap(47000, tolerance: 0.12), 48000)
        XCTAssertEqual(AudioInputRateEstimator.snap(15800, tolerance: 0.12), 16000)
        XCTAssertNil(AudioInputRateEstimator.snap(37000, tolerance: 0.12))
        XCTAssertNil(AudioInputRateEstimator.snap(0, tolerance: 0.12))
    }

    // MARK: - Relabel

    func testRelabelPreservesSamplesAndChangesRate() {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 2, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 480)!
        buffer.frameLength = 480
        for channel in 0..<2 {
            for frame in 0..<480 {
                buffer.floatChannelData![channel][frame] = Float(sin(Double(frame) * 0.1)) * (channel == 0 ? 1.0 : 0.5)
            }
        }

        guard let relabeled = buffer.relabeled(sampleRate: 24000) else {
            XCTFail("relabeled returned nil for a float32 buffer")
            return
        }

        XCTAssertEqual(relabeled.format.sampleRate, 24000)
        XCTAssertEqual(relabeled.format.channelCount, 2)
        XCTAssertEqual(relabeled.frameLength, 480)
        for channel in 0..<2 {
            for frame in 0..<480 {
                XCTAssertEqual(relabeled.floatChannelData![channel][frame], buffer.floatChannelData![channel][frame])
            }
        }
    }

    func testRelabelToSameRateReturnsEquivalent() {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 100)!
        buffer.frameLength = 100
        let result = buffer.relabeled(sampleRate: 48000)
        XCTAssertEqual(result?.format.sampleRate, 48000)
    }

    func testRelabeledBufferResamplesAtCorrectedRatio() {
        // A 24 kHz-labeled buffer of 480 frames should resample to ~320 frames at 16 kHz.
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 480)!
        buffer.frameLength = 480
        for frame in 0..<480 {
            buffer.floatChannelData![0][frame] = Float(sin(Double(frame) * 0.05))
        }

        guard let relabeled = buffer.relabeled(sampleRate: 24000),
              let data = AudioStreamResampler().resampledData(from: relabeled) else {
            XCTFail("relabel or resample failed")
            return
        }
        let frames = data.count / MemoryLayout<Float>.size
        // 480 * 16000/24000 = 320, allowing for converter priming on a single buffer.
        XCTAssertGreaterThan(frames, 250)
        XCTAssertLessThan(frames, 360)
    }
}
