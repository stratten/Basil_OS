import XCTest
@testable import BasilClient

final class PostProcessingProgressMathTests: XCTestCase {

    // Two synthetic tracks of 60s each (aggregate 120s). The bar must advance
    // monotonically across both with no reset between mic and system.
    func testAggregateProgressIsMonotonicAcrossTwoTracks() {
        let total = 120.0
        var previous = 0.0
        var values: [Double] = []

        // Track 1 streaming 0 -> 60s.
        for t in stride(from: 0.0, through: 60.0, by: 15.0) {
            let v = PostProcessingProgressMath.aggregateProgress(
                completedTrackSeconds: 0.0,
                currentTrackSeconds: t,
                aggregateTotalSeconds: total,
                previous: previous,
                fallbackPerTrack: t / 60.0
            )
            values.append(v)
            previous = v
        }
        // Track 1 completes -> 60s banked.
        previous = PostProcessingProgressMath.aggregateProgress(
            completedTrackSeconds: 60.0,
            currentTrackSeconds: 0.0,
            aggregateTotalSeconds: total,
            previous: previous,
            fallbackPerTrack: previous
        )
        values.append(previous)

        // Track 2 streaming 0 -> 60s (current resets, but banked seconds carry).
        for t in stride(from: 0.0, through: 60.0, by: 15.0) {
            let v = PostProcessingProgressMath.aggregateProgress(
                completedTrackSeconds: 60.0,
                currentTrackSeconds: t,
                aggregateTotalSeconds: total,
                previous: previous,
                fallbackPerTrack: t / 60.0
            )
            values.append(v)
            previous = v
        }

        // Monotonic non-decreasing.
        for i in 1..<values.count {
            XCTAssertGreaterThanOrEqual(values[i], values[i - 1], "Aggregate progress regressed at index \(i)")
        }
        // Midpoint after track 1 should be ~0.5 (60/120), not reset to 0.
        XCTAssertEqual(values.first(where: { $0 >= 0.5 }) ?? 0.0, 0.5, accuracy: 0.0001)
        // Ends at 100%.
        XCTAssertEqual(values.last ?? 0.0, 1.0, accuracy: 0.0001)
    }

    // Adversarial: single-track meeting where the aggregate total is unknown
    // (0) must fall back to per-track progress and still reach 100%.
    func testUnknownAggregateFallsBackToPerTrack() {
        let v0 = PostProcessingProgressMath.aggregateProgress(
            completedTrackSeconds: 0.0, currentTrackSeconds: 0.0,
            aggregateTotalSeconds: 0.0, previous: 0.0, fallbackPerTrack: 0.0
        )
        XCTAssertEqual(v0, 0.0, accuracy: 0.0001)

        let vMid = PostProcessingProgressMath.aggregateProgress(
            completedTrackSeconds: 0.0, currentTrackSeconds: 0.0,
            aggregateTotalSeconds: 0.0, previous: 0.0, fallbackPerTrack: 0.5
        )
        XCTAssertEqual(vMid, 0.5, accuracy: 0.0001)

        let vEnd = PostProcessingProgressMath.aggregateProgress(
            completedTrackSeconds: 0.0, currentTrackSeconds: 0.0,
            aggregateTotalSeconds: 0.0, previous: 0.5, fallbackPerTrack: 1.0
        )
        XCTAssertEqual(vEnd, 1.0, accuracy: 0.0001)
    }

    // Values are always clamped to 0...1 even if inputs overshoot.
    func testAggregateClampsToUnitInterval() {
        let v = PostProcessingProgressMath.aggregateProgress(
            completedTrackSeconds: 200.0, currentTrackSeconds: 50.0,
            aggregateTotalSeconds: 120.0, previous: 0.9, fallbackPerTrack: 0.0
        )
        XCTAssertEqual(v, 1.0, accuracy: 0.0001)
    }

    // Multi-source re-transcription replaces the per-file backend string with a
    // coherent "source i of n" label (so it no longer fights the aggregate clock).
    func testProgressLabelMultiSourceUsesSourceOfN() {
        let label = PostProcessingProgressMath.progressLabel(
            message: "Re-transcribing: 870s / 26:12",
            sourceIndex: 1,
            sourceTotal: 2
        )
        XCTAssertEqual(label, "Re-transcribing — source 1 of 2")
    }

    // Single-source re-transcription drops the count entirely.
    func testProgressLabelSingleSourceHasNoCount() {
        let label = PostProcessingProgressMath.progressLabel(
            message: "Re-transcribing: 12s / 00:30",
            sourceIndex: 1,
            sourceTotal: 1
        )
        XCTAssertEqual(label, "Re-transcribing")
    }

    // The Parakeet variant still begins with "Re-transcribing" and is mapped.
    func testProgressLabelParakeetVariantMapped() {
        let label = PostProcessingProgressMath.progressLabel(
            message: "Re-transcribing with Parakeet: chunk 2",
            sourceIndex: 2,
            sourceTotal: 2
        )
        XCTAssertEqual(label, "Re-transcribing — source 2 of 2")
    }

    // Non-transcription status messages pass through untouched (model loading,
    // diarizing, completion), regardless of the source counters.
    func testProgressLabelNonTranscriptionMessagesPassThrough() {
        XCTAssertEqual(
            PostProcessingProgressMath.progressLabel(
                message: "Loading Whisper model for re-transcription...",
                sourceIndex: 1, sourceTotal: 2
            ),
            "Loading Whisper model for re-transcription..."
        )
        XCTAssertEqual(
            PostProcessingProgressMath.progressLabel(
                message: "Identifying speakers...", sourceIndex: 1, sourceTotal: 2
            ),
            "Identifying speakers..."
        )
    }
}
