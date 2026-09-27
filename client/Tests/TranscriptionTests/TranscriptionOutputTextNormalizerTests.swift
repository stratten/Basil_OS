import XCTest
@testable import BasilClient

final class TranscriptionOutputTextNormalizerTests: XCTestCase {
    func testReturnsOriginalTextWhenNoRules() {
        XCTAssertEqual(
            TranscriptionOutputTextNormalizer.apply("hello world", rules: []),
            "hello world"
        )
    }

    func testReturnsOriginalTextWhenInputIsEmpty() {
        let rules = [TranscriptionTextReplacementRule(source: "slash", replacement: "/")]

        XCTAssertEqual(TranscriptionOutputTextNormalizer.apply("", rules: rules), "")
    }

    func testReplacesSingleWordCaseInsensitively() {
        let rules = [TranscriptionTextReplacementRule(source: "slash", replacement: "/")]

        XCTAssertEqual(
            TranscriptionOutputTextNormalizer.apply(
                "go slash home then SLASH again",
                rules: rules
            ),
            "go / home then / again"
        )
    }

    func testDoesNotMatchInsideALongerWord() {
        let rules = [TranscriptionTextReplacementRule(source: "slash", replacement: "/")]

        XCTAssertEqual(
            TranscriptionOutputTextNormalizer.apply(
                "do not backslash the slashed path",
                rules: rules
            ),
            "do not backslash the slashed path"
        )
    }

    func testReplacesMultiWordPhraseWithFlexibleWhitespace() {
        let rules = [TranscriptionTextReplacementRule(source: "new line", replacement: "\n")]

        XCTAssertEqual(
            TranscriptionOutputTextNormalizer.apply(
                "please open new  line here",
                rules: rules
            ),
            "please open \n here"
        )
    }

    func testLongerSourceWinsOverOverlappingShorterSource() {
        let rules = [
            TranscriptionTextReplacementRule(source: "new", replacement: "incorrect"),
            TranscriptionTextReplacementRule(source: "new line", replacement: "\n"),
        ]

        XCTAssertEqual(
            TranscriptionOutputTextNormalizer.apply("start new line end", rules: rules),
            "start \n end"
        )
    }

    func testReplacementTextIsNotRecursivelyRematched() {
        let rules = [
            TranscriptionTextReplacementRule(source: "a", replacement: "a a"),
            TranscriptionTextReplacementRule(source: "a a", replacement: "incorrect"),
        ]

        XCTAssertEqual(
            TranscriptionOutputTextNormalizer.apply("a", rules: rules),
            "a a"
        )
    }

    func testPreservesEmptyReplacementText() {
        let rules = [
            TranscriptionTextReplacementRule(source: "filler word", replacement: ""),
        ]

        XCTAssertEqual(
            TranscriptionOutputTextNormalizer.apply(
                "please remove filler word",
                rules: rules
            ),
            "please remove "
        )
    }
}
