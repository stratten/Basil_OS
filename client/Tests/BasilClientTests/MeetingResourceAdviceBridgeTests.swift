import XCTest
@testable import BasilClient

@MainActor
final class MeetingResourceAdviceBridgeTests: XCTestCase {
    func testEveryThermalStateHasAStableName() {
        XCTAssertEqual(MeetingThermalStateName.name(for: .nominal), "nominal")
        XCTAssertEqual(MeetingThermalStateName.name(for: .fair), "fair")
        XCTAssertEqual(MeetingThermalStateName.name(for: .serious), "serious")
        XCTAssertEqual(MeetingThermalStateName.name(for: .critical), "critical")
    }

    func testSnapshotCarriesTheCurrentThermalState() throws {
        let viewModel = LiveTranscriptionViewModel()
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })
        publisher.sendSnapshot(to: token)
        let ui = try XCTUnwrap(events.last?.ui)
        XCTAssertEqual(ui.thermalState, MeetingThermalStateName.name(for: ProcessInfo.processInfo.thermalState))
        let data = try JSONEncoder().encode(ui)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["thermalState"] as? String, ui.thermalState)
    }

    func testThermalStateIsOptionalWhenDecodingAnOlderPayload() throws {
        let viewModel = LiveTranscriptionViewModel()
        let publisher = MeetingBridgePublisher(viewModel: viewModel)
        let token = MeetingPresentationToken(id: UUID())
        var events: [MeetingBridgeEvent] = []
        publisher.attach(token: token, sink: { events.append($0) }, meterSink: { _ in })
        publisher.sendSnapshot(to: token)
        var ui = try XCTUnwrap(events.last?.ui)
        ui.thermalState = nil
        let data = try JSONEncoder().encode(ui)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertNil(object["thermalState"])
        XCTAssertEqual(try JSONDecoder().decode(MeetingUIStateDTO.self, from: data).thermalState, nil)
    }

    func testOpenAppSettingsIsInTheClosedList() {
        XCTAssertEqual(MeetingBridgeIntent(rawValue: "openAppSettings"), .openAppSettings)
        XCTAssertNil(MeetingBridgeIntent(rawValue: "openSettings"))
    }
}
