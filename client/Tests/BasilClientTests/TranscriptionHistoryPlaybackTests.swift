import XCTest
@testable import BasilClient

@MainActor
final class TranscriptionHistoryPlaybackTests: XCTestCase {
    func testClampedSeekTargetKeepsNormalValues() {
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(42.5, duration: 100), 42.5)
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(0, duration: 100), 0)
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(100, duration: 100), 100)
    }

    func testClampedSeekTargetClampsNegativeAndPastTheEnd() {
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(-5, duration: 100), 0)
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(250, duration: 100), 100)
    }

    func testClampedSeekTargetTreatsNonFiniteInputAndUnknownDurationAsTheStart() {
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(.nan, duration: 100), 0)
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(.infinity, duration: 100), 0)
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(10, duration: 0), 0)
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(10, duration: .nan), 0)
        XCTAssertEqual(TranscriptionHistoryViewModel.clampedSeekTarget(10, duration: -3), 0)
    }

    func testSeekWithNothingPlayingIsIgnoredAndReportsNothing() {
        let viewModel = TranscriptionHistoryViewModel()
        var reported: [TranscriptionHistoryViewModel.PlaybackProgress] = []
        viewModel.onPlaybackProgress = { reported.append($0) }
        viewModel.seekAudio(toSeconds: 12)
        XCTAssertTrue(reported.isEmpty)
    }

    func testParseSeekRequestAcceptsAnIdAndFiniteNonNegativeSeconds() {
        let parsed = ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "tx-1", "seconds": NSNumber(value: 12.5)])
        XCTAssertEqual(parsed?.transcriptionId, "tx-1")
        XCTAssertEqual(parsed?.seconds, 12.5)
        XCTAssertEqual(ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "tx-1", "seconds": NSNumber(value: 0)])?.seconds, 0)
    }

    func testParseSeekRequestRejectsMalformedBodies() {
        XCTAssertNil(ReactTranscriptionHistoryWebView.parseSeekRequest([:]))
        XCTAssertNil(ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "", "seconds": NSNumber(value: 1)]))
        XCTAssertNil(ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "tx-1"]))
        XCTAssertNil(ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "tx-1", "seconds": "12"]))
        XCTAssertNil(ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "tx-1", "seconds": NSNumber(value: -1)]))
        XCTAssertNil(ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "tx-1", "seconds": NSNumber(value: Double.nan)]))
        XCTAssertNil(ReactTranscriptionHistoryWebView.parseSeekRequest(["transcriptionId": "tx-1", "seconds": NSNumber(value: Double.infinity)]))
    }

    func testPlaybackProgressEventCarriesTheIdPositionAndDuration() {
        let event = ReactTranscriptionHistoryWebView.playbackProgressEvent(
            .init(transcriptionID: "tx-1", positionSeconds: 3.25, durationSeconds: 125)
        )
        XCTAssertEqual(event["type"] as? String, "playbackProgress")
        XCTAssertEqual(event["transcriptionId"] as? String, "tx-1")
        XCTAssertEqual(event["positionSeconds"] as? Double, 3.25)
        XCTAssertEqual(event["durationSeconds"] as? Double, 125)
    }
}
