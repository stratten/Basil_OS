import XCTest
@testable import BasilClient

final class ProfileEditorRequestTests: XCTestCase {
    func testWindowKeySeparatesEditorModesAndIdentifiers() {
        XCTAssertEqual(
            ProfileEditorRequest.skill(slug: "inspect-pdf").windowKey,
            "skill:inspect-pdf"
        )
        XCTAssertEqual(
            ProfileEditorRequest.skillCandidate(id: "inspect-pdf").windowKey,
            "skill_candidate:inspect-pdf"
        )
        XCTAssertEqual(
            ProfileEditorRequest.memoryFile(name: "MEMORY.md").windowKey,
            "memory_file:MEMORY.md"
        )
    }
}
