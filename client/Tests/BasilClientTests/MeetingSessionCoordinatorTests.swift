import XCTest
@testable import BasilClient

@MainActor
final class MeetingSessionCoordinatorTests: XCTestCase {
    func testDetectedMeetingLaunchReservationSuppressesDuplicateDetection() {
        let coordinator = MeetingSessionCoordinator()

        XCTAssertFalse(coordinator.shouldSuppressDetectedMeetingPrompt)
        XCTAssertTrue(coordinator.reserveDetectedMeetingLaunch())
        XCTAssertTrue(coordinator.shouldSuppressDetectedMeetingPrompt)
        XCTAssertFalse(coordinator.reserveDetectedMeetingLaunch())
    }

    func testActiveRecordingSuppressesDetectedMeetingLaunchReservation() {
        let coordinator = MeetingSessionCoordinator()
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        defer { coordinator.detachPresentation(token) }

        coordinator.viewModel?.isRecording = true

        XCTAssertTrue(coordinator.shouldSuppressDetectedMeetingPrompt)
        XCTAssertFalse(coordinator.reserveDetectedMeetingLaunch())
    }

    func testTearingDownLastPresentationClearsDetectedMeetingLaunchReservation() {
        let coordinator = MeetingSessionCoordinator()
        XCTAssertTrue(coordinator.reserveDetectedMeetingLaunch())
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })

        coordinator.detachPresentation(token)

        XCTAssertFalse(coordinator.shouldSuppressDetectedMeetingPrompt)
        XCTAssertTrue(coordinator.reserveDetectedMeetingLaunch())
    }

    func testInitializationLoadsHistoryBeforeBackendModelWarmup() async {
        var completedSteps: [String] = []
        let initializationFinished = expectation(description: "session initialization finished")
        let operations = MeetingSessionInitializationOperations(
            loadMeetingHistory: { _ in completedSteps.append("history") },
            initialize: { _ in completedSteps.append("initialize") },
            loadAvailableModels: { _ in completedSteps.append("transcriptionModels") },
            loadAnalysisModels: { _ in
                completedSteps.append("analysisModels")
                initializationFinished.fulfill()
            }
        )
        let coordinator = MeetingSessionCoordinator(initializationOperations: operations)
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })

        await fulfillment(of: [initializationFinished], timeout: 1)

        XCTAssertEqual(completedSteps, ["history", "initialize", "transcriptionModels", "analysisModels"])
        coordinator.detachPresentation(token)
    }

    func testFirstWebAttachCreatesSessionAndSecondAttachReusesIt() {
        let coordinator = MeetingSessionCoordinator()
        let firstToken = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        let firstModel = coordinator.viewModel
        XCTAssertNotNil(firstModel)

        var receivedEvents: [MeetingBridgeEvent] = []
        let secondToken = coordinator.attachWebPresentation(
            sink: { receivedEvents.append($0) },
            meterSink: { _ in }
        )
        XCTAssertTrue(coordinator.viewModel === firstModel, "second attach must reuse the same session")
        XCTAssertTrue(receivedEvents.isEmpty, "snapshot must wait until React installs its bridge handler")
        coordinator.webPresentationDidBecomeReady(secondToken)
        XCTAssertFalse(receivedEvents.isEmpty, "ready presentation must receive an authoritative snapshot")
        XCTAssertEqual(receivedEvents.first?.type, MeetingBridgeEventType.snapshot)

        coordinator.detachPresentation(firstToken)
        XCTAssertNotNil(coordinator.viewModel, "session must survive while any presentation remains attached")

        coordinator.detachPresentation(secondToken)
        XCTAssertNil(coordinator.viewModel, "session must be torn down once every presentation has detached")
    }

    func testDetachingOneWebPresentationDoesNotResetSharedState() {
        let coordinator = MeetingSessionCoordinator()
        let firstToken = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        let secondToken = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })

        coordinator.viewModel?.meetingName = "Grounded Test Meeting"
        coordinator.detachPresentation(firstToken)

        XCTAssertEqual(coordinator.viewModel?.meetingName, "Grounded Test Meeting")
        coordinator.detachPresentation(secondToken)
    }

    func testReadyHandshakeReplaysAuthoritativeSnapshotAfterRendererReload() {
        let coordinator = MeetingSessionCoordinator()
        var receivedEvents: [MeetingBridgeEvent] = []
        let token = coordinator.attachWebPresentation(
            sink: { receivedEvents.append($0) },
            meterSink: { _ in }
        )

        coordinator.viewModel?.meetingName = "Before reload"
        coordinator.webPresentationDidBecomeReady(token)
        coordinator.viewModel?.meetingName = "After reload"
        coordinator.webPresentationDidBecomeReady(token)

        let snapshots = receivedEvents.filter { $0.type == MeetingBridgeEventType.snapshot }
        XCTAssertEqual(snapshots.count, 2)
        XCTAssertEqual(snapshots.last?.revision, 0)
        XCTAssertEqual(snapshots.last?.ui?.meetingName, "After reload")
    }

    func testStaleProcessIntentDoesNotPartiallyMutateAudioConfiguration() {
        let coordinator = MeetingSessionCoordinator()
        var receivedEvents: [MeetingBridgeEvent] = []
        _ = coordinator.attachWebPresentation(
            sink: { receivedEvents.append($0) },
            meterSink: { _ in }
        )
        coordinator.viewModel?.enableMicrophone = false
        coordinator.viewModel?.systemAudioCaptureMode = .none

        coordinator.handleWebIntent(
            .setAudioSource,
            payload: [
                "enableMicrophone": true,
                "captureMode": SystemAudioCaptureMode.selectedProcess.rawValue,
                "processId": 999_999,
            ]
        )

        XCTAssertEqual(coordinator.viewModel?.enableMicrophone, false)
        XCTAssertEqual(coordinator.viewModel?.systemAudioCaptureMode, SystemAudioCaptureMode.none)
        XCTAssertEqual(receivedEvents.last?.type, MeetingBridgeEventType.validationError)
        XCTAssertEqual(receivedEvents.last?.validationErrorCode, "stale_process")
    }

    func testSidebarIntentMutatesAndPersistsStateWithoutNativeRenderer() {
        let coordinator = MeetingSessionCoordinator()
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        guard let viewModel = coordinator.viewModel else {
            XCTFail("attaching a presentation must create the shared view model")
            return
        }
        defer {
            viewModel.setSidebarCollapsed(false)
            coordinator.detachPresentation(token)
        }
        viewModel.setSidebarCollapsed(false)

        coordinator.handleWebIntent(
            .setSidebarCollapsed,
            payload: ["collapsed": true]
        )

        XCTAssertTrue(viewModel.isSidebarCollapsed)
        XCTAssertTrue(viewModel.storedSidebarCollapsed)
    }

    func testSearchFilterIntentAssignsCompleteValidatedValue() {
        let coordinator = MeetingSessionCoordinator()
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        defer { coordinator.viewModel?.meetingSearchTask?.cancel(); coordinator.detachPresentation(token) }

        coordinator.handleWebIntent(
            .setMeetingSearchFilters,
            payload: [
                "queryMode": "or",
                "name": "Review",
                "nameMode": "and",
                "purpose": "",
                "purposeMode": "and",
                "participants": "Miriam,Alex",
                "participantsMode": "or",
                "transcript": "opportunity,stage",
                "transcriptMode": "and",
                "source": "Zoom",
                "sourceMode": "and",
                "startDate": "2026-01-01",
                "endDate": "2026-01-31",
                "processing": "complete",
                "analysis": "has_analysis",
            ]
        )

        XCTAssertEqual(coordinator.viewModel?.meetingSearchFilters.participantsMode, .or)
        XCTAssertEqual(coordinator.viewModel?.meetingSearchFilters.transcript, "opportunity,stage")
        XCTAssertEqual(coordinator.viewModel?.meetingSearchFilters.processing, .complete)
    }

    func testSearchFilterIntentAcceptsOmittedOptionalDates() {
        let coordinator = MeetingSessionCoordinator()
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        defer { coordinator.viewModel?.meetingSearchTask?.cancel(); coordinator.detachPresentation(token) }

        coordinator.handleWebIntent(
            .setMeetingSearchFilters,
            payload: [
                "queryMode": "and",
                "name": "",
                "nameMode": "and",
                "purpose": "",
                "purposeMode": "and",
                "participants": "Miriam",
                "participantsMode": "and",
                "transcript": "opportunity,stage",
                "transcriptMode": "and",
                "source": "",
                "sourceMode": "and",
                "processing": "any",
                "analysis": "any",
            ]
        )

        XCTAssertEqual(coordinator.viewModel?.meetingSearchFilters.participants, "Miriam")
        XCTAssertEqual(coordinator.viewModel?.meetingSearchFilters.transcript, "opportunity,stage")
        XCTAssertNil(coordinator.viewModel?.meetingSearchFilters.startDate)
        XCTAssertNil(coordinator.viewModel?.meetingSearchFilters.endDate)
    }

    func testMalformedSearchFilterIntentDoesNotPartiallyMutateState() {
        let coordinator = MeetingSessionCoordinator()
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        defer { coordinator.detachPresentation(token) }
        let original = coordinator.viewModel?.meetingSearchFilters

        coordinator.handleWebIntent(
            .setMeetingSearchFilters,
            payload: ["queryMode": "invalid"]
        )

        XCTAssertEqual(coordinator.viewModel?.meetingSearchFilters, original)
    }

    func testMalformedAutomationIntentDoesNotPartiallyMutateConfiguration() {
        let coordinator = MeetingSessionCoordinator()
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        coordinator.viewModel?.sessionAutoRetranscribeOnStop = false

        coordinator.handleWebIntent(
            .setAutomation,
            payload: [
                "autoRetranscribeOnStop": true,
                "autoAnalyzeTiming": "not-a-supported-timing",
            ]
        )

        XCTAssertEqual(coordinator.viewModel?.sessionAutoRetranscribeOnStop, false)
        coordinator.detachPresentation(token)
    }

    func testDeleteMeetingIntentRejectsTheActiveAnalysisOwner() {
        let coordinator = MeetingSessionCoordinator()
        var receivedEvents: [MeetingBridgeEvent] = []
        let token = coordinator.attachWebPresentation(
            sink: { receivedEvents.append($0) },
            meterSink: { _ in }
        )
        guard let viewModel = coordinator.viewModel else {
            XCTFail("attaching a presentation must create the shared view model")
            return
        }
        defer { coordinator.detachPresentation(token) }
        let meetingId = "active-analysis-meeting"
        viewModel.meetings = [
            MeetingListItem(
                id: meetingId,
                name: "Active analysis",
                purpose: nil,
                participants: [],
                startTime: "2026-01-01T00:00:00Z",
                endTime: nil,
                durationSeconds: nil,
                audioPath: nil,
                transcriptPath: nil,
                isPostProcessed: false,
                analysisSummary: nil,
                sessionId: nil,
                audioSource: nil,
                members: nil
            )
        ]
        viewModel.isAnalyzing = true
        viewModel.activeAnalysisMeetingId = meetingId

        coordinator.handleWebIntent(.deleteMeeting, payload: ["meetingId": meetingId])

        XCTAssertEqual(receivedEvents.last?.type, MeetingBridgeEventType.validationError)
        XCTAssertEqual(receivedEvents.last?.validationErrorCode, "analysis_active")
    }
}
