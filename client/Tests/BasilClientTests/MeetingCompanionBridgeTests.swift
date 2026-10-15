import XCTest
@testable import BasilClient

@MainActor
final class MeetingCompanionBridgeTests: XCTestCase {
    private func makePublisher() -> (LiveTranscriptionViewModel, MeetingBridgePublisher, MeetingPresentationToken, () -> MeetingUIStateDTO?) {
        let viewModel = LiveTranscriptionViewModel()
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })
        let latestUI: () -> MeetingUIStateDTO? = {
            publisher.sendSnapshot(to: token)
            return events.last?.ui
        }
        return (viewModel, publisher, token, latestUI)
    }

    func testSnapshotCarriesRecordingMeetingIdOnlyWhileRecording() {
        let (viewModel, _, _, latestUI) = makePublisher()
        viewModel.microphoneMeetingId = "mic-1"
        viewModel.systemAudioMeetingId = "sys-1"

        viewModel.isRecording = false
        XCTAssertNil(latestUI()?.recordingMeetingId)

        viewModel.isRecording = true
        XCTAssertEqual(latestUI()?.recordingMeetingId, "mic-1")

        viewModel.microphoneMeetingId = nil
        XCTAssertEqual(latestUI()?.recordingMeetingId, "sys-1")
    }

    func testSnapshotCarriesTheBackendPort() {
        let (_, _, _, latestUI) = makePublisher()
        XCTAssertEqual(latestUI()?.companionApiPort, APIClient.shared.currentPort)
    }

    func testUIStateEncodesTheCompanionFields() throws {
        let (viewModel, _, _, latestUI) = makePublisher()
        viewModel.isRecording = true
        viewModel.microphoneMeetingId = "mic-1"
        let ui = try XCTUnwrap(latestUI())
        let data = try JSONEncoder().encode(ui)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["recordingMeetingId"] as? String, "mic-1")
        XCTAssertNotNil(object["companionApiPort"] as? Int)
    }

    func testCompanionIntentsAreInTheClosedList() {
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "pickCompanionFolder"), .pickCompanionFolder)
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "openCompanionWindow"), .openCompanionWindow)
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "openCompanionAssistantSession"), .openCompanionAssistantSession)
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "setCompanionPaneExtent"), .setCompanionPaneExtent)
    }

    func testProtocolVersionIsUnchanged() {
        XCTAssertEqual(meetingBridgeProtocolVersion, 4)
    }
}
