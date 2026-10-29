import AVFoundation
import Foundation

/// Estimates the true input sample rate of an audio stream from the actual
/// frame throughput of the capture callbacks, independent of any declared
/// device/tap format.
///
/// Motivation: a CoreAudio tap reports its format once (`kAudioTapPropertyFormat`),
/// but the aggregate device can be clocked by an output device (e.g. AirPods)
/// whose real rate differs - and changes mid-session when the Bluetooth profile
/// switches. Trusting the frozen declared rate then resamples at the wrong ratio
/// and time-compresses the audio (the "chipmunk" artifact). Measuring throughput
/// is robust regardless of what any property claims.
///
/// Design for safety:
/// - Seeded with the declared rate, so before the first window completes the
///   reported rate equals today's behavior.
/// - Snaps measurements to the nearest standard rate, and only when the relative
///   error is small; an unreliable measurement keeps the current rate.
/// - Requires a candidate to repeat across `confirmCount` windows before it is
///   adopted (hysteresis), so jitter cannot flip the rate.
///
/// Not thread-safe: call `observe(frameCount:)` from a single serial context
/// (the recorder's IO block), matching `AudioStreamResampler`.
final class AudioInputRateEstimator {
    private static let context = "AudioInputRateEstimator"
    private static let standardRates: [Double] = [
        8000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000
    ]

    private let windowSeconds: Double
    private let snapTolerance: Double
    private let confirmCount: Int
    private let now: () -> UInt64

    private(set) var estimatedSampleRate: Double = 48000
    private var declaredSampleRate: Double = 48000

    private var windowStart: UInt64?
    private var windowFrames: UInt64 = 0
    private var pendingCandidate: Double = 0
    private var pendingStreak: Int = 0
    private var stableWindowCount: Int = 0

    init(
        windowSeconds: Double = 1.0,
        snapTolerance: Double = 0.12,
        confirmCount: Int = 2,
        now: @escaping () -> UInt64 = { DispatchTime.now().uptimeNanoseconds }
    ) {
        self.windowSeconds = windowSeconds
        self.snapTolerance = snapTolerance
        self.confirmCount = confirmCount
        self.now = now
    }

    /// Seeds the estimator with the stream's declared rate and clears all
    /// measurement state. Call once per capture start.
    func reset(declaredSampleRate: Double) {
        self.declaredSampleRate = declaredSampleRate > 0 ? declaredSampleRate : 48000
        self.estimatedSampleRate = self.declaredSampleRate
        windowStart = nil
        windowFrames = 0
        pendingCandidate = 0
        pendingStreak = 0
        stableWindowCount = 0
    }

    /// Records one delivered buffer's frame count and returns the current best
    /// estimate of the true input sample rate. Cheap; safe to call every callback.
    @discardableResult
    func observe(frameCount: AVAudioFrameCount) -> Double {
        let nowNanos = now()

        guard let start = windowStart else {
            windowStart = nowNanos
            windowFrames = UInt64(frameCount)
            return estimatedSampleRate
        }

        windowFrames += UInt64(frameCount)

        let elapsedNanos = nowNanos >= start ? nowNanos - start : 0
        let elapsedSeconds = Double(elapsedNanos) / 1_000_000_000.0
        guard elapsedSeconds >= windowSeconds else {
            return estimatedSampleRate
        }

        let measuredRate = elapsedSeconds > 0 ? Double(windowFrames) / elapsedSeconds : 0
        evaluate(measuredRate: measuredRate)

        windowStart = nowNanos
        windowFrames = 0
        return estimatedSampleRate
    }

    private func evaluate(measuredRate: Double) {
        guard let snapped = Self.snap(measuredRate, tolerance: snapTolerance) else {
            pendingCandidate = 0
            pendingStreak = 0
            #if DEBUG
            DevLogger.shared.info(
                "[RateDiag] measured=\(Int(measuredRate)) Hz (no standard match) keeping=\(Int(estimatedSampleRate)) Hz declared=\(Int(declaredSampleRate)) Hz",
                context: Self.context
            )
            #endif
            return
        }

        if snapped == estimatedSampleRate {
            pendingCandidate = 0
            pendingStreak = 0
            stableWindowCount += 1
            #if DEBUG
            if stableWindowCount <= 2 || stableWindowCount % 15 == 0 {
                DevLogger.shared.info(
                    "[RateDiag] measured=\(Int(measuredRate)) Hz stable=\(Int(estimatedSampleRate)) Hz declared=\(Int(declaredSampleRate)) Hz",
                    context: Self.context
                )
            }
            #endif
            return
        }

        stableWindowCount = 0

        if snapped == pendingCandidate {
            pendingStreak += 1
        } else {
            pendingCandidate = snapped
            pendingStreak = 1
        }

        if pendingStreak >= confirmCount {
            let previous = estimatedSampleRate
            estimatedSampleRate = snapped
            pendingCandidate = 0
            pendingStreak = 0
            #if DEBUG
            DevLogger.shared.info(
                "[RateDiag] confirmed switch \(Int(previous)) -> \(Int(snapped)) Hz (measured=\(Int(measuredRate)) declared=\(Int(declaredSampleRate)))",
                context: Self.context
            )
            #endif
        } else {
            #if DEBUG
            DevLogger.shared.info(
                "[RateDiag] candidate=\(Int(snapped)) Hz streak=\(pendingStreak)/\(confirmCount) (measured=\(Int(measuredRate)) current=\(Int(estimatedSampleRate)))",
                context: Self.context
            )
            #endif
        }
    }

    /// Returns the nearest standard rate to `rate`, or nil if the closest
    /// standard rate is farther than `tolerance` (relative), meaning the
    /// measurement is unreliable and should be ignored.
    static func snap(_ rate: Double, tolerance: Double) -> Double? {
        guard rate > 0 else { return nil }
        var best: Double?
        var bestError = Double.greatestFiniteMagnitude
        for standard in standardRates {
            let error = abs(rate - standard) / standard
            if error < bestError {
                bestError = error
                best = standard
            }
        }
        guard let best, bestError <= tolerance else { return nil }
        return best
    }
}
