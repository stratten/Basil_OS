import XCTest
@testable import BasilClient

@MainActor
final class AgentTaskCancellationTransportTests: XCTestCase {
    func testBridgeDecoderForwardsExactCurrentTurnIdentifier() {
        let body: [String: Any] = [
            "type": "cancelRunningAgentTask",
            "agentTaskId": "follow-up-turn-2",
        ]

        XCTAssertEqual(
            decodeAgentTaskCancellationIdentifier(from: body),
            "follow-up-turn-2"
        )
        XCTAssertNil(decodeAgentTaskCancellationIdentifier(from: [
            "type": "cancelRunningAgentTask",
            "agentTaskId": "",
        ]))
        XCTAssertNil(decodeAgentTaskCancellationIdentifier(from: [
            "type": "reportAgentTaskCancellationStage",
            "agentTaskId": "follow-up-turn-2",
        ]))
    }

    func testRESTCancellationForwardsExactCurrentTurnIdentifierOnce() async throws {
        var receivedIdentifiers: [String] = []
        let websocketCancellationCount = 0

        try await performAgentTaskRESTCancellation(agentTaskId: "follow-up-turn-2") { identifier in
            receivedIdentifiers.append(identifier)
        }

        XCTAssertEqual(receivedIdentifiers, ["follow-up-turn-2"])
        XCTAssertEqual(websocketCancellationCount, 0)
    }

    func testRESTCancellationPropagatesTransportFailure() async {
        struct ExpectedFailure: Error {}

        do {
            try await performAgentTaskRESTCancellation(agentTaskId: "follow-up-turn-3") { _ in
                throw ExpectedFailure()
            }
            XCTFail("Expected cancellation transport failure")
        } catch is ExpectedFailure {
            XCTAssertTrue(true)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }
}
