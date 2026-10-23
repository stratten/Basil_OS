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

    func testFocusTranscriptIntentRaisesNotetakerAndBroadcastsRequest() {
        let coordinator = MeetingSessionCoordinator()
        var receivedEvents: [MeetingBridgeEvent] = []
        var raised: [MeetingFocusTarget] = []
        coordinator.focusWindowRaiser = { raised.append($0) }
        let token = coordinator.attachWebPresentation(sink: { receivedEvents.append($0) }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(token)

        coordinator.handleWebIntent(.focusTranscript, payload: ["itemId": "item-1", "startSeconds": 12.5, "endSeconds": 18])

        XCTAssertEqual(raised, [.transcript])
        let request = receivedEvents.last?.focusRequest
        XCTAssertEqual(receivedEvents.last?.type, MeetingBridgeEventType.focusRequest)
        XCTAssertEqual(request?.target, "transcript")
        XCTAssertEqual(request?.itemId, "item-1")
        XCTAssertEqual(request?.startSeconds, 12.5)
        XCTAssertEqual(request?.endSeconds, 18)
    }

    func testFocusCompanionItemIntentRaisesCompanionAndRepeatedRequestsGetNewNonces() {
        let coordinator = MeetingSessionCoordinator()
        var receivedEvents: [MeetingBridgeEvent] = []
        var raised: [MeetingFocusTarget] = []
        coordinator.focusWindowRaiser = { raised.append($0) }
        let token = coordinator.attachWebPresentation(sink: { receivedEvents.append($0) }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(token)

        coordinator.handleWebIntent(.focusCompanionItem, payload: ["itemId": "item-9"])
        coordinator.handleWebIntent(.focusCompanionItem, payload: ["itemId": "item-9"])

        XCTAssertEqual(raised, [.companion, .companion])
        let requests = receivedEvents.compactMap(\.focusRequest)
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests.first?.target, "companion")
        XCTAssertNil(requests.first?.startSeconds)
        XCTAssertNotEqual(requests.first?.nonce, requests.last?.nonce)
    }

    func testMalformedFocusIntentsRaiseNothingAndReportValidationError() {
        let coordinator = MeetingSessionCoordinator()
        var receivedEvents: [MeetingBridgeEvent] = []
        var raised: [MeetingFocusTarget] = []
        coordinator.focusWindowRaiser = { raised.append($0) }
        _ = coordinator.attachWebPresentation(sink: { receivedEvents.append($0) }, meterSink: { _ in })

        coordinator.handleWebIntent(.focusTranscript, payload: ["itemId": "item-1", "startSeconds": 9, "endSeconds": 3])
        coordinator.handleWebIntent(.focusTranscript, payload: ["itemId": "item-1", "startSeconds": -1, "endSeconds": 3])
        coordinator.handleWebIntent(.focusTranscript, payload: ["itemId": "item-1"])
        coordinator.handleWebIntent(.focusCompanionItem, payload: ["itemId": ""])
        coordinator.handleWebIntent(.focusCompanionItem, payload: [:])

        XCTAssertTrue(raised.isEmpty)
        XCTAssertTrue(receivedEvents.compactMap(\.focusRequest).isEmpty)
        XCTAssertEqual(receivedEvents.filter { $0.type == MeetingBridgeEventType.validationError }.count, 5)
        XCTAssertEqual(receivedEvents.last?.validationErrorCode, "focus_request_invalid")
    }

    func testFocusRequestIsReplayedToAPresentationThatBecomesReadyAfterwards() {
        let coordinator = MeetingSessionCoordinator()
        var lateEvents: [MeetingBridgeEvent] = []
        coordinator.focusWindowRaiser = { _ in }
        let firstToken = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(firstToken)
        coordinator.handleWebIntent(.focusCompanionItem, payload: ["itemId": "item-3"])

        let lateToken = coordinator.attachWebPresentation(sink: { lateEvents.append($0) }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(lateToken)

        XCTAssertEqual(lateEvents.map(\.type), [MeetingBridgeEventType.snapshot, MeetingBridgeEventType.focusRequest])
        XCTAssertEqual(lateEvents.last?.revision, 1)
        XCTAssertEqual(lateEvents.last?.focusRequest?.itemId, "item-3")
    }

    func testStaleFocusRequestIsNotReplayed() throws {
        let viewModel = LiveTranscriptionViewModel()
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })
        let request = MeetingFocusRequest(target: .companion, payload: ["itemId": "item-3"])
        let issuedAt = Date(timeIntervalSince1970: 1_000)
        publisher.publishFocusRequest(try XCTUnwrap(request), now: issuedAt)
        events.removeAll()

        publisher.replayRecentFocusRequest(to: token, now: issuedAt.addingTimeInterval(MeetingBridgePublisher.focusRequestReplaySeconds + 1))

        XCTAssertTrue(events.isEmpty)
    }

    // MARK: - Detached Companion window

    func testCompanionWindowFlagFlipsAndReachesEveryPresentationAsADelta() {
        let coordinator = MeetingSessionCoordinator()
        var first: [MeetingBridgeEvent] = []
        var second: [MeetingBridgeEvent] = []
        let firstToken = coordinator.attachWebPresentation(sink: { first.append($0) }, meterSink: { _ in })
        let secondToken = coordinator.attachWebPresentation(sink: { second.append($0) }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(firstToken)
        coordinator.webPresentationDidBecomeReady(secondToken)
        XCTAssertEqual(first.last?.ui?.isCompanionWindowOpen, false)

        coordinator.companionWindowPresenceDidChange(open: true)
        XCTAssertTrue(coordinator.isCompanionWindowOpen)
        XCTAssertEqual(first.last?.type, MeetingBridgeEventType.sessionDelta)
        XCTAssertEqual(first.last?.ui?.isCompanionWindowOpen, true)
        XCTAssertEqual(second.last?.ui?.isCompanionWindowOpen, true)

        coordinator.companionWindowPresenceDidChange(open: false)
        XCTAssertFalse(coordinator.isCompanionWindowOpen)
        XCTAssertEqual(first.last?.ui?.isCompanionWindowOpen, false)
        XCTAssertEqual(second.last?.ui?.isCompanionWindowOpen, false)
    }

    func testRepeatingTheSameCompanionWindowStateSendsNothingMore() {
        let coordinator = MeetingSessionCoordinator()
        var events: [MeetingBridgeEvent] = []
        let token = coordinator.attachWebPresentation(sink: { events.append($0) }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(token)
        coordinator.companionWindowPresenceDidChange(open: true)
        let count = events.count
        coordinator.companionWindowPresenceDidChange(open: true)
        XCTAssertEqual(events.count, count, "a renderer reload reports ready again; the same state must not broadcast twice")
    }

    func testAWindowAttachedAfterTheCompanionOpenedSeesItInItsSnapshot() {
        let coordinator = MeetingSessionCoordinator()
        _ = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        coordinator.companionWindowPresenceDidChange(open: true)

        var late: [MeetingBridgeEvent] = []
        let lateToken = coordinator.attachWebPresentation(sink: { late.append($0) }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(lateToken)
        XCTAssertEqual(late.first?.type, MeetingBridgeEventType.snapshot)
        XCTAssertEqual(late.first?.ui?.isCompanionWindowOpen, true)
    }

    func testARecreatedSessionKeepsTheCompanionWindowFlag() {
        let coordinator = MeetingSessionCoordinator()
        let token = coordinator.attachWebPresentation(sink: { _ in }, meterSink: { _ in })
        coordinator.companionWindowPresenceDidChange(open: true)
        coordinator.detachPresentation(token)
        XCTAssertNil(coordinator.bridgePublisher, "every presentation detached, so the publisher is gone")

        var events: [MeetingBridgeEvent] = []
        let nextToken = coordinator.attachWebPresentation(sink: { events.append($0) }, meterSink: { _ in })
        coordinator.webPresentationDidBecomeReady(nextToken)
        XCTAssertEqual(events.first?.ui?.isCompanionWindowOpen, true)
    }
}
