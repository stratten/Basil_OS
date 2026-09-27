import AppKit
import XCTest
@testable import BasilClient

final class MeetingBridgeContractTests: XCTestCase {
    func testMeetingBridgeEventEncodesOnlyRelevantFieldsForType() throws {
        let event = MeetingBridgeEvent(
            type: MeetingBridgeEventType.transcriptDelta,
            revision: 3,
            selectionGeneration: 1,
            transcript: [
                TranscriptLineDTO(
                    id: "line-1",
                    text: "hello",
                    speakerId: "speaker0",
                    isInterim: false,
                    displayStart: "0:03",
                    timelineStartSeconds: 3,
                    timelineEndSeconds: 4,
                    source: "Microphone",
                    lineComplete: true
                )
            ]
        )
        let data = try JSONEncoder().encode(event)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(object?["type"] as? String, "transcriptDelta")
        XCTAssertEqual(object?["revision"] as? Int, 3)
        XCTAssertNil(object?["ui"], "sessionDelta-only fields must stay absent from a transcriptDelta payload")
        let transcript = object?["transcript"] as? [[String: Any]]
        XCTAssertEqual(transcript?.first?["id"] as? String, "line-1")
    }

    func testTranscriptPatchEncodesOrderedIDsUpsertsAndRemovedIDs() throws {
        let line = TranscriptLineDTO(
            id: "line-2",
            text: "updated",
            speakerId: nil,
            isInterim: false,
            displayStart: "0:04",
            timelineStartSeconds: 4,
            timelineEndSeconds: 5,
            source: "Microphone",
            lineComplete: true
        )
        let event = MeetingBridgeEvent(
            type: MeetingBridgeEventType.transcriptDelta,
            revision: 3,
            selectionGeneration: 1,
            transcriptPatch: TranscriptPatchDTO(
                orderedIDs: ["line-2"],
                upserts: [line],
                removedIDs: ["line-1"]
            )
        )

        let data = try JSONEncoder().encode(event)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let patch = try XCTUnwrap(object["transcriptPatch"] as? [String: Any])
        XCTAssertNil(object["transcript"])
        XCTAssertEqual(patch["orderedIDs"] as? [String], ["line-2"])
        XCTAssertEqual((patch["upserts"] as? [[String: Any]])?.first?["id"] as? String, "line-2")
        XCTAssertEqual(patch["removedIDs"] as? [String], ["line-1"])
    }

    @MainActor
    func testMeterUpdatesDoNotProduceRevisionedBridgeEvents() async {
        let viewModel = LiveTranscriptionViewModel()
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        var meterPayloads: [MeetingMeterPayload] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { meterPayloads.append($0) })
        publisher.sendSnapshot(to: token)
        events.removeAll()
        meterPayloads.removeAll()

        viewModel.updateMicrophoneAudioLevel(0.75)
        viewModel.updateSystemAudioLevel(0.25)
        await Task.yield()

        XCTAssertTrue(events.isEmpty)
        XCTAssertEqual(meterPayloads.last?.microphoneAudioLevel, 0.75)
        XCTAssertEqual(meterPayloads.last?.systemAudioLevel, 0.25)
    }

    @MainActor
    func testMeterUpdateMethodsClampValues() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.updateMicrophoneAudioLevel(-1)
        viewModel.updateSystemAudioLevel(2)

        XCTAssertEqual(viewModel.microphoneAudioLevel, 0)
        XCTAssertEqual(viewModel.systemAudioLevel, 1)
    }

    func testMeetingBridgeIntentRawValuesMatchClosedList() {
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "reactReady"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "chromeHeight"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "promoteProposalToTodo"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "startProposalNow"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "openProposalTodo"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "openProposalAgentTask"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "promoteAllProposalsToTodos"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "loadMoreMeetings"))
        XCTAssertNotNil(MeetingBridgeIntent(rawValue: "setMeetingSearchFilters"))
        XCTAssertNil(MeetingBridgeIntent(rawValue: "notARealIntent"))
    }

    func testAestheticWebPayloadIncludesMeetingSurfaceTokens() {
        let payload = AestheticWebPayload.themePayload()
        for key in [
            "backgroundPrimary",
            "backgroundSecondary",
            "backgroundTertiary",
            "textPrimary",
            "textSecondary",
            "textTertiary",
            "separatorColor",
            "fieldBorder",
        ] {
            XCTAssertNotNil(payload[key], "Missing shared WebKit theme token: \(key)")
        }
    }

    func testAestheticWebPayloadResolvesSemanticColorsAgainstConfiguredBackground() {
        let lightAppearance = AestheticWebPayload.semanticAppearance(for: .white)
        let darkAppearance = AestheticWebPayload.semanticAppearance(for: .black)
        XCTAssertEqual(lightAppearance.name, .aqua)
        XCTAssertEqual(darkAppearance.name, .darkAqua)
        XCTAssertNotEqual(
            AestheticWebPayload.colorToHex(AestheticSystem.Colors.backgroundSecondary, appearance: lightAppearance),
            AestheticWebPayload.colorToHex(AestheticSystem.Colors.backgroundSecondary, appearance: darkAppearance)
        )
        XCTAssertNotEqual(
            AestheticWebPayload.colorToHex(AestheticSystem.Colors.textSecondary, appearance: lightAppearance),
            AestheticWebPayload.colorToHex(AestheticSystem.Colors.textSecondary, appearance: darkAppearance)
        )
    }

    func testAestheticWebPayloadPreservesSeparatorOpacityForCSS() {
        let translucentBlack = NSColor(srgbRed: 0, green: 0, blue: 0, alpha: 0.1)
        XCTAssertEqual(
            AestheticWebPayload.colorToCSS(translucentBlack),
            "rgba(0, 0, 0, 0.100)"
        )
    }

    @MainActor
    func testSnapshotNormalizesMultiSourceRetranscriptionProgressLabel() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.isPostProcessing = true
        viewModel.postProcessingMessage = "Re-transcribing: 12s / 00:30"
        viewModel.postProcessingSourceIndex = 1
        viewModel.postProcessingSourceTotal = 2
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })

        publisher.sendSnapshot(to: token)

        XCTAssertEqual(events.last?.ui?.postProcessingMessage, "Re-transcribing — source 1 of 2")
    }

    @MainActor
    func testFreshMeetingDoesNotClaimBackgroundWorkOwnedByAnotherMeeting() {
        let viewModel = LiveTranscriptionViewModel()
        viewModel.isPostProcessing = true
        viewModel.activePostProcessingMeetingId = "meeting-a"
        viewModel.selectedMeetingId = nil
        viewModel.microphoneMeetingId = nil
        viewModel.systemAudioMeetingId = nil
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })

        publisher.sendSnapshot(to: token)

        XCTAssertEqual(events.last?.ui?.activePostProcessingMeetingId, "meeting-a")
        XCTAssertNil(events.last?.ui?.displayedMeetingWorkOwnerId)
    }

    @MainActor
    func testDatePreferenceChangesRepublishHistoryWithoutChangingSelectionGeneration() async throws {
        let store = DateDisplayPreferenceStore.shared
        let originalStyle = store.style
        defer { store.update(originalStyle) }
        store.update(.relative)

        let timestamp = ISO8601DateFormatter().string(from: Date())
        let item = MeetingListItem(
            id: "meeting-1",
            name: "Preference Test",
            purpose: nil,
            participants: [],
            startTime: timestamp,
            endTime: nil,
            durationSeconds: 60,
            audioPath: nil,
            transcriptPath: nil,
            isPostProcessed: false,
            analysisSummary: nil,
            sessionId: nil,
            audioSource: nil,
            members: nil
        )
        let viewModel = LiveTranscriptionViewModel()
        viewModel.meetings = [item]
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })
        publisher.sendSnapshot(to: token)

        XCTAssertEqual(events.last?.history?.first?.formattedDate, item.displayDate)
        XCTAssertEqual(events.last?.selectionGeneration, 0)
        let initialDTO = try XCTUnwrap(events.last?.history?.first)
        let encoded = try JSONEncoder().encode(initialDTO)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertEqual(object["formattedDate"] as? String, item.displayDate)

        store.update(.absolute)
        await Task.yield()
        await Task.yield()
        let absoluteDelta = try XCTUnwrap(events.last(where: { $0.type == MeetingBridgeEventType.historyDelta }))
        XCTAssertEqual(absoluteDelta.history?.first?.formattedDate, DateFormattingUtils.formatTimestamp(timestamp, style: .absolute))
        XCTAssertEqual(absoluteDelta.selectionGeneration, 0)

        let deltaCount = events.filter { $0.type == MeetingBridgeEventType.historyDelta }.count
        store.update(.relative)
        await Task.yield()
        await Task.yield()
        XCTAssertEqual(events.filter { $0.type == MeetingBridgeEventType.historyDelta }.count, deltaCount + 1)
        XCTAssertEqual(events.last?.history?.first?.formattedDate, DateFormattingUtils.formatTimestamp(timestamp, style: .relative))
        XCTAssertEqual(events.last?.selectionGeneration, 0)
    }

    @MainActor
    func testAnalysisSummaryRefreshPublishesSidebarHistoryDelta() async throws {
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let viewModel = LiveTranscriptionViewModel()
        viewModel.meetings = [
            MeetingListItem(
                id: "meeting-1",
                name: "Analysis Refresh",
                purpose: nil,
                participants: [],
                startTime: timestamp,
                endTime: nil,
                durationSeconds: 60,
                audioPath: nil,
                transcriptPath: nil,
                isPostProcessed: true,
                analysisSummary: nil,
                sessionId: nil,
                audioSource: nil,
                members: nil
            )
        ]
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        let historyDeltaReceived = expectation(description: "analysis summary publishes a history delta")
        publisher.attach(
            token: token,
            sink: { event in
                events.append(event)
                if event.type == MeetingBridgeEventType.historyDelta {
                    historyDeltaReceived.fulfill()
                }
            },
            meterSink: { _ in }
        )
        publisher.sendSnapshot(to: token)

        viewModel.meetings = [
            MeetingListItem(
                id: "meeting-1",
                name: "Analysis Refresh",
                purpose: nil,
                participants: [],
                startTime: timestamp,
                endTime: nil,
                durationSeconds: 60,
                audioPath: nil,
                transcriptPath: nil,
                isPostProcessed: true,
                analysisSummary: AnalysisSummary(
                    count: 1,
                    latestFilename: "analysis.json",
                    latestTimestamp: timestamp,
                    pendingActionCount: 2
                ),
                sessionId: nil,
                audioSource: nil,
                members: nil
            )
        ]
        await fulfillment(of: [historyDeltaReceived], timeout: 1)

        let historyDelta = try XCTUnwrap(events.last(where: { $0.type == MeetingBridgeEventType.historyDelta }))
        XCTAssertEqual(historyDelta.history?.first?.analysisSummary?.count, 1)
        XCTAssertEqual(historyDelta.history?.first?.analysisSummary?.latestFilename, "analysis.json")
    }
}
