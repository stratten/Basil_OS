import XCTest
@testable import BasilClient

final class TranscriptFragmentJoinTests: XCTestCase {
    func testBareWordsGetOneSpace() {
        XCTAssertEqual(TranscriptFragmentJoin.join("whatever", "time"), "whatever time")
        XCTAssertEqual(TranscriptFragmentJoin.join("thirteen", "Yeah"), "thirteen Yeah")
    }

    func testLeadingOrTrailingWhitespaceIsNotDoubled() {
        XCTAssertEqual(TranscriptFragmentJoin.join("whatever", " time"), "whatever time")
        XCTAssertEqual(TranscriptFragmentJoin.join("whatever ", "time"), "whatever time")
    }

    func testClosingPunctuationAttachesToThePreviousWord() {
        XCTAssertEqual(TranscriptFragmentJoin.join("discuss", ","), "discuss,")
        XCTAssertEqual(TranscriptFragmentJoin.join("really", "?"), "really?")
    }

    func testEmptySidesReturnTheOtherSide() {
        XCTAssertEqual(TranscriptFragmentJoin.join("", "hello"), "hello")
        XCTAssertEqual(TranscriptFragmentJoin.join("hello", ""), "hello")
    }
}
