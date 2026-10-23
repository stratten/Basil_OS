import XCTest
@testable import BasilClient

final class CompanionAssistantSessionRequestTests: XCTestCase {
    func testAValidPayloadKeepsBothTexts() throws {
        let request = try XCTUnwrap(CompanionAssistantSessionRequest(payload: ["instruction": "Talk through the renewal options.", "contextText": "The renewal date is 3 March."]))
        XCTAssertEqual(request.instruction, "Talk through the renewal options.")
        XCTAssertEqual(request.contextText, "The renewal date is 3 March.")
    }

    func testBothTextsAreTrimmed() throws {
        let request = try XCTUnwrap(CompanionAssistantSessionRequest(payload: ["instruction": "  Plan the call.\n", "contextText": "\n  Some context.  "]))
        XCTAssertEqual(request.instruction, "Plan the call.")
        XCTAssertEqual(request.contextText, "Some context.")
    }

    func testAMissingOrBlankInstructionIsRefused() {
        XCTAssertNil(CompanionAssistantSessionRequest(payload: ["contextText": "context"]))
        XCTAssertNil(CompanionAssistantSessionRequest(payload: ["instruction": "   \n", "contextText": "context"]))
    }

    func testANonStringInstructionOrContextIsRefused() {
        XCTAssertNil(CompanionAssistantSessionRequest(payload: ["instruction": 42, "contextText": "context"]))
        XCTAssertNil(CompanionAssistantSessionRequest(payload: ["instruction": "Plan the call.", "contextText": 7]))
    }

    func testAnOverlongInstructionIsRefusedInsteadOfCut() {
        let longInstruction = String(repeating: "a", count: CompanionAssistantSessionRequest.maxInstructionCharacters + 1)
        XCTAssertNil(CompanionAssistantSessionRequest(payload: ["instruction": longInstruction]))
        let limit = String(repeating: "a", count: CompanionAssistantSessionRequest.maxInstructionCharacters)
        XCTAssertEqual(CompanionAssistantSessionRequest(payload: ["instruction": limit])?.instruction, limit)
    }

    func testAnOverlongContextIsCutToTheLimit() throws {
        let longContext = String(repeating: "b", count: CompanionAssistantSessionRequest.maxContextCharacters + 500)
        let request = try XCTUnwrap(CompanionAssistantSessionRequest(payload: ["instruction": "Plan the call.", "contextText": longContext]))
        XCTAssertEqual(request.contextText.count, CompanionAssistantSessionRequest.maxContextCharacters)
    }

    func testAMissingOrBlankContextUsesTheFallbackSentence() throws {
        let missing = try XCTUnwrap(CompanionAssistantSessionRequest(payload: ["instruction": "Plan the call."]))
        XCTAssertEqual(missing.contextText, CompanionAssistantSessionRequest.fallbackContext)
        let blank = try XCTUnwrap(CompanionAssistantSessionRequest(payload: ["instruction": "Plan the call.", "contextText": "  \n "]))
        XCTAssertEqual(blank.contextText, CompanionAssistantSessionRequest.fallbackContext)
    }
}
