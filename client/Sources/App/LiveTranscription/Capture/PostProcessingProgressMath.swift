import Foundation

/// Pure progress math for retranscription, extracted so the combined-duration
/// behaviour can be unit-tested without instantiating the view model.
enum PostProcessingProgressMath {

    /// Combined-duration progress across the sequential tracks of one job.
    ///
    /// - Parameters:
    ///   - completedTrackSeconds: total duration of tracks already finished.
    ///   - currentTrackSeconds: elapsed audio within the in-flight track.
    ///   - aggregateTotalSeconds: summed duration of every track in the job.
    ///   - previous: last reported aggregate value (used to keep it monotonic).
    ///   - fallbackPerTrack: per-track 0->1 value to use when the aggregate
    ///     total is unknown (e.g. a just-stopped live meeting not yet listed).
    /// - Returns: a clamped, non-decreasing aggregate in 0...1.
    static func aggregateProgress(
        completedTrackSeconds: Double,
        currentTrackSeconds: Double,
        aggregateTotalSeconds: Double,
        previous: Double,
        fallbackPerTrack: Double
    ) -> Double {
        guard aggregateTotalSeconds > 0 else {
            return min(1.0, max(0.0, fallbackPerTrack))
        }
        let combined = (completedTrackSeconds + currentTrackSeconds) / aggregateTotalSeconds
        return min(1.0, max(previous, combined))
    }

    /// Compose the left-hand progress-row label.
    ///
    /// The backend emits a per-FILE "Re-transcribing: <elapsed> / <thisFileTotal>"
    /// message while the duration clock on the right is the cross-SOURCE
    /// aggregate; pairing them produced the mismatched denominators the user saw
    /// (per-file 26:12 next to aggregate 52:26). During the active
    /// re-transcription phase we replace the per-file string with a coherent
    /// "source i of n" label (the aggregate clock supplies the timing); every
    /// other status message (model loading, diarizing, etc.) passes through
    /// unchanged.
    static func progressLabel(
        message: String,
        sourceIndex: Int,
        sourceTotal: Int
    ) -> String {
        guard message.hasPrefix("Re-transcribing") else {
            return message
        }
        if sourceTotal > 1 {
            return "Re-transcribing — source \(sourceIndex) of \(sourceTotal)"
        }
        return "Re-transcribing"
    }
}
