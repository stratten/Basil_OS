import XCTest
@testable import BasilClient

final class LiveTranscriptionTypesTests: XCTestCase {
    func testAudioErrorDescriptionsAreUserReadable() {
        let cases: [(AudioError, String)] = [
            (.engineSetupFailed, "Failed to set up audio engine"),
            (.invalidFormat, "Failed to create audio format"),
            (.recordingFailed, "Failed to start recording"),
            (.permissionDenied, "System audio permission denied")
        ]

        for (error, expectedDescription) in cases {
            XCTAssertEqual(error.errorDescription, expectedDescription)
            XCTAssertEqual(error.localizedDescription, expectedDescription)
        }
    }
}
