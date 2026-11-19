import XCTest
@testable import BasilClient

@MainActor
final class MeetingAutoEndCountdownTests: XCTestCase {
    private let bundle = "us.zoom.xos"

    private func autoStartedRecording() -> LiveTranscriptionViewModel {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.autoStartedBundleID = bundle
        viewModel.isRecording = true
        return viewModel
    }

    func testCountdownShowsOnTheRecordingDetectionStarted() {
        let viewModel = autoStartedRecording()
        let deadline = Date().addingTimeInterval(25)

        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: deadline, totalSeconds: 25)

        XCTAssertEqual(viewModel.autoEndCountdown, AutoEndCountdown(deadline: deadline, totalSeconds: 25))
    }

    func testCountdownIsIgnoredForAManualRecordingAndForAnotherApp() {
        let manual = LiveTranscriptionViewModel()
        manual.isRecording = true
        manual.beginAutoEndCountdown(bundleID: bundle, deadline: Date().addingTimeInterval(25), totalSeconds: 25)
        XCTAssertNil(manual.autoEndCountdown, "a manual recording is never ended automatically")

        let viewModel = autoStartedRecording()
        viewModel.beginAutoEndCountdown(bundleID: "com.microsoft.teams2", deadline: Date().addingTimeInterval(25), totalSeconds: 25)
        XCTAssertNil(viewModel.autoEndCountdown)
    }

    func testCountdownIsIgnoredWhenNothingIsRecording() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.autoStartedBundleID = bundle

        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: Date().addingTimeInterval(25), totalSeconds: 25)

        XCTAssertNil(viewModel.autoEndCountdown)
    }

    func testAudioReturningClearsTheCountdown() {
        let viewModel = autoStartedRecording()
        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: Date().addingTimeInterval(25), totalSeconds: 25)

        viewModel.endAutoEndCountdown(bundleID: "com.microsoft.teams2")
        XCTAssertNotNil(viewModel.autoEndCountdown, "another app's audio says nothing about this meeting")

        viewModel.endAutoEndCountdown(bundleID: bundle)
        XCTAssertNil(viewModel.autoEndCountdown)
    }

    func testDismissingKeepsTheRecordingRunningThroughTheBackendEnd() {
        let viewModel = autoStartedRecording()
        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: Date().addingTimeInterval(25), totalSeconds: 25)

        viewModel.dismissAutoEnd()

        XCTAssertNil(viewModel.autoEndCountdown)
        XCTAssertFalse(viewModel.shouldFinalizeForAutoEnd(bundleID: bundle), "the backend's meeting_ended must no longer stop this recording")
        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: Date().addingTimeInterval(25), totalSeconds: 25)
        XCTAssertNil(viewModel.autoEndCountdown, "a later quiet spell in the same meeting does not bring the countdown back")
    }

    func testAPausedRecordingStillShowsTheCountdownAndCanBeDismissed() {
        let viewModel = autoStartedRecording()
        viewModel.isCapturePaused = true
        let deadline = Date().addingTimeInterval(25)

        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: deadline, totalSeconds: 25)
        XCTAssertEqual(viewModel.autoEndCountdown, AutoEndCountdown(deadline: deadline, totalSeconds: 25))
        XCTAssertTrue(viewModel.shouldFinalizeForAutoEnd(bundleID: bundle), "pausing capture does not exempt a recording from the automatic end")

        viewModel.dismissAutoEnd()
        XCTAssertNil(viewModel.autoEndCountdown)
        XCTAssertFalse(viewModel.shouldFinalizeForAutoEnd(bundleID: bundle))
    }

    func testTheNextRecordingStartsWithAutoEndArmedAgain() {
        let viewModel = autoStartedRecording()
        viewModel.dismissAutoEnd()

        viewModel.isRecording = false
        viewModel.autoStartedBundleID = bundle
        viewModel.isRecording = true

        XCTAssertTrue(viewModel.shouldFinalizeForAutoEnd(bundleID: bundle))
    }

    func testStoppingReleasesTheMeetingAppSoALaterManualRecordingIsNeverEndedByIt() {
        let viewModel = autoStartedRecording()

        viewModel.isRecording = false
        viewModel.isRecording = true

        XCTAssertNil(viewModel.autoStartedBundleID)
        XCTAssertFalse(viewModel.shouldFinalizeForAutoEnd(bundleID: bundle))
    }

    func testACalendarLaunchedRecordingAdoptsTheCallsAppAndThenEndsWithIt() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.isRecording = true
        viewModel.isAwaitingAutoEndSource = true
        XCTAssertFalse(viewModel.shouldFinalizeForAutoEnd(bundleID: bundle), "no app is bound yet")

        XCTAssertTrue(viewModel.adoptAutoEndSource(bundleID: bundle))

        XCTAssertTrue(viewModel.shouldFinalizeForAutoEnd(bundleID: bundle))
        let deadline = Date().addingTimeInterval(25)
        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: deadline, totalSeconds: 25)
        XCTAssertEqual(viewModel.autoEndCountdown, AutoEndCountdown(deadline: deadline, totalSeconds: 25))
    }

    func testOnlyTheFirstDetectedAppIsAdoptedAndNeverForAManualRecording() {
        let manual = LiveTranscriptionViewModel()
        manual.isRecording = true
        XCTAssertFalse(manual.adoptAutoEndSource(bundleID: bundle))
        XCTAssertFalse(manual.shouldFinalizeForAutoEnd(bundleID: bundle))

        let calendarLaunch = LiveTranscriptionViewModel()
        calendarLaunch.isRecording = true
        calendarLaunch.isAwaitingAutoEndSource = true
        XCTAssertFalse(calendarLaunch.adoptAutoEndSource(bundleID: ""), "an empty bundle ID names no app")
        XCTAssertTrue(calendarLaunch.adoptAutoEndSource(bundleID: bundle))
        XCTAssertFalse(calendarLaunch.adoptAutoEndSource(bundleID: "com.microsoft.teams2"), "a second app does not replace the first")
        XCTAssertEqual(calendarLaunch.autoStartedBundleID, bundle)
    }

    func testAnAutoStartedRecordingKeepsItsAppWhenAnotherIsDetected() {
        let viewModel = autoStartedRecording()
        viewModel.isAwaitingAutoEndSource = true

        XCTAssertFalse(viewModel.adoptAutoEndSource(bundleID: "com.microsoft.teams2"))
        XCTAssertEqual(viewModel.autoStartedBundleID, bundle)
    }

    func testStoppingClearsTheWaitForACallsApp() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.isRecording = true
        viewModel.isAwaitingAutoEndSource = true

        viewModel.isRecording = false

        XCTAssertFalse(viewModel.isAwaitingAutoEndSource)
        XCTAssertFalse(viewModel.adoptAutoEndSource(bundleID: bundle))
    }

    func testStoppingClearsAVisibleCountdown() {
        let viewModel = autoStartedRecording()
        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: Date().addingTimeInterval(25), totalSeconds: 25)

        viewModel.isRecording = false

        XCTAssertNil(viewModel.autoEndCountdown)
    }

    func testPublisherSendsTheDeadlineToTheMeetingWindow() {
        let viewModel = autoStartedRecording()
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })
        let deadline = Date(timeIntervalSince1970: 2_000)
        viewModel.beginAutoEndCountdown(bundleID: bundle, deadline: deadline, totalSeconds: 25)

        publisher.sendSnapshot(to: token)

        XCTAssertEqual(events.last?.ui?.autoEndCountdown, AutoEndCountdownDTO(deadlineEpochMs: 2_000_000, totalSeconds: 25))
    }

    func testDismissIntentIsInTheClosedList() {
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "dismissAutoEnd"), .dismissAutoEnd)
    }
}
