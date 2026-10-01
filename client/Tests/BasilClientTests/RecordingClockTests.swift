import XCTest
@testable import BasilClient

private final class ManualTime: @unchecked Sendable {
    var value: TimeInterval = 100
}

final class RecordingClockTests: XCTestCase {
    private func makeClock() -> (RecordingClock, ManualTime) {
        let time = ManualTime()
        return (RecordingClock(now: { time.value }), time)
    }

    func testElapsedExcludesPausedSpans() {
        let (clock, time) = makeClock()
        clock.start()
        time.value += 10
        clock.pause()
        XCTAssertTrue(clock.isPaused)
        time.value += 300
        XCTAssertEqual(clock.elapsedSeconds(), 10, accuracy: 0.0001)
        clock.resume()
        time.value += 5
        XCTAssertEqual(clock.elapsedSeconds(), 15, accuracy: 0.0001)
        XCTAssertTrue(clock.isRunning)
    }

    func testStopFreezesElapsedAndStartResets() {
        let (clock, time) = makeClock()
        clock.start()
        time.value += 42
        clock.stop()
        time.value += 100
        XCTAssertEqual(clock.elapsedSeconds(), 42, accuracy: 0.0001)
        XCTAssertFalse(clock.isPaused)
        clock.resume()
        XCTAssertFalse(clock.isRunning, "a stopped clock must not resume")
        clock.start()
        XCTAssertEqual(clock.elapsedSeconds(), 0, accuracy: 0.0001)
    }

    func testPauseAndResumeAreIdempotent() {
        let (clock, time) = makeClock()
        clock.resume()
        XCTAssertFalse(clock.isRunning, "resume before start is ignored")
        clock.start()
        time.value += 3
        clock.pause()
        clock.pause()
        time.value += 3
        clock.resume()
        clock.resume()
        time.value += 1
        XCTAssertEqual(clock.elapsedSeconds(), 4, accuracy: 0.0001)
    }

    func testMarkersAreSpacedPerSourceAndResettable() {
        let (clock, _) = makeClock()
        clock.start()
        XCTAssertTrue(clock.claimMarker(for: .microphone, at: 0.1))
        XCTAssertFalse(clock.claimMarker(for: .microphone, at: 1.0))
        XCTAssertTrue(clock.claimMarker(for: .systemAudio, at: 1.0))
        XCTAssertTrue(clock.claimMarker(for: .microphone, at: 2.2))
        clock.resetMarker(for: .microphone)
        XCTAssertTrue(clock.claimMarker(for: .microphone, at: 2.3))
        XCTAssertFalse(clock.claimMarker(for: .microphone, at: .nan))
        clock.pause()
        XCTAssertFalse(clock.claimMarker(for: .systemAudio, at: 10), "no markers while paused")
    }

    func testControlMessagesAreValidJSON() throws {
        let marker = LiveTranscriptionViewModel.streamClockMarkerMessage(elapsedSeconds: 12.34567)
        let markerObject = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(marker.utf8)) as? [String: Any])
        XCTAssertEqual(markerObject["type"] as? String, "native_stream_clock")
        XCTAssertEqual(markerObject["elapsed_seconds"] as? Double ?? -1, 12.3457, accuracy: 0.00001)

        let negative = LiveTranscriptionViewModel.streamClockMarkerMessage(elapsedSeconds: -5)
        let negativeObject = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(negative.utf8)) as? [String: Any])
        XCTAssertEqual(negativeObject["elapsed_seconds"] as? Double, 0)

        let paused = LiveTranscriptionViewModel.captureStateControlMessage(paused: true)
        let pausedObject = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(paused.utf8)) as? [String: Any])
        XCTAssertEqual(pausedObject["type"] as? String, "native_capture_state")
        XCTAssertEqual(pausedObject["paused"] as? Bool, true)

        let live = LiveTranscriptionViewModel.liveTranscriptionControlMessage(enabled: false)
        let liveObject = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(live.utf8)) as? [String: Any])
        XCTAssertEqual(liveObject["type"] as? String, "native_live_transcription")
        XCTAssertEqual(liveObject["enabled"] as? Bool, false)
    }

    func testControlMessagesNeverContainLegacyTerminationWords() {
        let messages = [
            LiveTranscriptionViewModel.streamClockMarkerMessage(elapsedSeconds: 1),
            LiveTranscriptionViewModel.captureStateControlMessage(paused: true),
            LiveTranscriptionViewModel.captureStateControlMessage(paused: false),
            LiveTranscriptionViewModel.liveTranscriptionControlMessage(enabled: true),
            LiveTranscriptionViewModel.liveTranscriptionControlMessage(enabled: false),
        ]
        for message in messages {
            for word in ["close", "terminate", "kill_process", "force_terminate"] {
                XCTAssertFalse(message.contains(word), "\(message) must not trigger the backend's legacy termination check")
            }
        }
    }
}
