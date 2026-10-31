import XCTest
@testable import BasilClient

final class RetranscriptionModelPreloadTests: XCTestCase {
    func testPreloadsWhenCadenceAndLiveTranscriptionAreOnAndModelIsSet() {
        XCTAssertTrue(RetranscriptionModelPreload.shouldPreload(cadenceEnabled: true, liveTranscriptionEnabled: true, model: "Parakeet"))
    }

    func testSkipsWhenCadenceIsOff() {
        XCTAssertFalse(RetranscriptionModelPreload.shouldPreload(cadenceEnabled: false, liveTranscriptionEnabled: true, model: "Parakeet"))
    }

    func testSkipsWhenLiveTranscriptionIsOff() {
        XCTAssertFalse(RetranscriptionModelPreload.shouldPreload(cadenceEnabled: true, liveTranscriptionEnabled: false, model: "Parakeet"))
    }

    func testSkipsWhenModelIsEmptyOrWhitespace() {
        XCTAssertFalse(RetranscriptionModelPreload.shouldPreload(cadenceEnabled: true, liveTranscriptionEnabled: true, model: ""))
        XCTAssertFalse(RetranscriptionModelPreload.shouldPreload(cadenceEnabled: true, liveTranscriptionEnabled: true, model: "  \n"))
    }

    func testRequestTargetsTheStaticPreloadPathWithTheModelBody() throws {
        let request = try XCTUnwrap(RetranscriptionModelPreload.makeRequest(port: 8000, model: "Parakeet v3"))

        XCTAssertEqual(request.url?.absoluteString, "http://localhost:8000/meetings/prepare-retranscription-model")
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        XCTAssertEqual(request.timeoutInterval, RetranscriptionModelPreload.requestTimeoutSeconds)
        let body = try XCTUnwrap(request.httpBody)
        let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
        XCTAssertEqual(decoded, ["model": "Parakeet v3"])
    }
}
