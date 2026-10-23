import XCTest
@testable import BasilClient

final class TranscriptSentenceBreakTests: XCTestCase {

    private let minWords = 5

    // MARK: - Positive cases

    func testPeriodEndsSentence() {
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "We should check the outbound email log.", minWords: minWords))
    }

    func testQuestionMarkEndsSentence() {
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "Do you know how to do that?", minWords: minWords))
    }

    func testExclamationEndsSentence() {
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "That was a lot of fun!", minWords: minWords))
    }

    func testTrailingClosingQuoteStillCounts() {
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "and then he said \"I do not know.\"", minWords: minWords))
    }

    func testTrailingWhitespaceIgnored() {
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "Either way that is fine.   ", minWords: minWords))
    }

    func testCapitalizedWordEndingSentenceIsNotTreatedAsInitial() {
        // Real sentence ending in an all-caps word should still break.
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "We are putting it on AWS.", minWords: minWords))
    }

    // MARK: - Minimum-word gate

    func testShortBackchannelStaysOpen() {
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary("Okay.", minWords: minWords))
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary("Yeah.", minWords: minWords))
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary("Thank you, thank you.", minWords: minWords))
    }

    func testExactlyMinWordsBreaks() {
        // "one two three four five." == 5 words.
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "one two three four five.", minWords: minWords))
    }

    func testBelowMinWordsDoesNotBreak() {
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "one two three four.", minWords: minWords))
    }

    func testLowerKnobSplitsShortSentences() {
        // The knob is the single tuning lever: a low minWords splits backchannels.
        XCTAssertTrue(TranscriptSentenceBreak.endsAtSentenceBoundary("Okay.", minWords: 1))
    }

    // MARK: - Negative cases (no boundary)

    func testMidSentenceDoesNotBreak() {
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "So then do a start time of whenever you know before", minWords: minWords))
    }

    func testTrailingCommaDoesNotBreak() {
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "In this case we only want the outbound,", minWords: minWords))
    }

    func testDecimalDoesNotBreak() {
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "We need to upgrade to version 3.", minWords: minWords))
    }

    func testSingleLetterInitialDoesNotBreak() {
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "I sent the message to B.", minWords: minWords))
    }

    func testAbbreviationUSDoesNotBreak() {
        // Final "S." of "U.S." is a lone capital preceded by a period.
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary(
            "They are based in the U.S.", minWords: minWords))
    }

    func testEmptyStringDoesNotBreak() {
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary("", minWords: minWords))
        XCTAssertFalse(TranscriptSentenceBreak.endsAtSentenceBoundary("    ", minWords: minWords))
    }
}
