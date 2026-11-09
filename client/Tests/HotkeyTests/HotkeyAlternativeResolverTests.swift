import XCTest
@testable import BasilClient

final class HotkeyAlternativeResolverTests: XCTestCase {
    private let rows = HotkeyTestSupport.rows

    private func alternative(
        _ id: String,
        table: [String: HotkeyBinding]? = nil,
        system: HotkeySystemState = HotkeyTestSupport.system()
    ) -> HotkeyBinding? {
        HotkeyAlternativeResolver.alternative(for: id, bindings: table ?? HotkeyTestSupport.defaultTable(), rows: rows, system: system)
    }

    func testTheClashingDefaultF8GetsTheFirstFreeChord() {
        let result = alternative("conversation_toggle", system: HotkeyTestSupport.system(functionKeysAreStandard: false))

        XCTAssertEqual(result?.key, "C")
        XCTAssertEqual(result?.modifiers, ["control", "option"])
        XCTAssertEqual(result?.isDoublePress, false)
    }

    func testACandidateThatClashesWithAMacShortcutIsSkipped() {
        let system = HotkeyTestSupport.system(
            functionKeysAreStandard: false,
            symbolic: HotkeyTestSupport.symbolic("999", keyCode: 8, mask: 262_144 + 524_288)
        )

        let result = alternative("conversation_toggle", system: system)

        XCTAssertEqual(result?.key, "C")
        XCTAssertEqual(result?.modifiers, ["control", "option", "shift"])
    }

    func testACandidateAnotherBasilRowAlreadyUsesIsSkippedEvenWhenThatRowComesLater() {
        var table = HotkeyTestSupport.defaultTable()
        table["home_board_toggle"] = HotkeyTestSupport.chord("C", ["control", "option"])

        let result = alternative("conversation_toggle", table: table, system: HotkeyTestSupport.system(functionKeysAreStandard: false))

        XCTAssertEqual(result?.modifiers, ["control", "option", "shift"])
    }

    func testTheCurrentKeysAreNeverProposedAsTheirOwnReplacement() {
        var table = HotkeyTestSupport.defaultTable()
        table["agent_task"] = HotkeyTestSupport.chord("Space", ["option", "shift"])

        let result = alternative("agent_task", table: table)

        XCTAssertEqual(result?.modifiers, ["control", "option"])
    }

    func testAnUnknownOrMissingRowHasNoAlternative() {
        XCTAssertNil(alternative("capture_screen"))
        XCTAssertNil(alternative("not_a_row", table: [:]))
    }

    func testNoAlternativeWhenEveryCandidateIsTaken() {
        var table = HotkeyTestSupport.defaultTable()
        table["insert_assistant_output"] = HotkeyTestSupport.doublePress("control")
        table["streaming_transcription"] = HotkeyTestSupport.doublePress("shift")

        XCTAssertNil(alternative("transcribe_audio", table: table))
    }

    func testSeveralRowsAreNeverGivenTheSameReplacement() {
        let result = HotkeyAlternativeResolver.alternatives(
            for: ["transcribe_audio", "assistant_session"],
            bindings: HotkeyTestSupport.defaultTable(),
            rows: rows,
            system: HotkeyTestSupport.system(siri: HotkeyTestSupport.unreadableSiri)
        )

        XCTAssertEqual(result["transcribe_audio"]?.doublePressKey, "control")
        XCTAssertEqual(result["assistant_session"]?.doublePressKey, "shift")
    }

    func testEveryCandidateIsSafeToTypeAndHasKeys() throws {
        for id in ["transcribe_audio", "assistant_session", "agent_task", "conversation_toggle", "home_board_toggle"] {
            let candidates = HotkeyAlternativeResolver.candidates(for: id)
            XCTAssertFalse(candidates.isEmpty, id)
            for candidate in candidates {
                XCTAssertTrue(candidate.enabled, id)
                XCTAssertNoThrow(try SetupHotkeyPayload.validate(candidate), "\(id) \(candidate.displayString)")
            }
        }
        XCTAssertTrue(HotkeyAlternativeResolver.candidates(for: "capture_screen").isEmpty)
    }

    func testNoCandidateIsAnotherRowsCurrentDefault() {
        let defaultsOfOtherRows = rows.map { HotkeyRowCatalog.defaultBinding(for: $0.id) }
        for id in ["agent_task", "conversation_toggle", "home_board_toggle"] {
            for candidate in HotkeyAlternativeResolver.candidates(for: id) {
                XCTAssertFalse(defaultsOfOtherRows.contains { HotkeyConflictEvaluator.collides(candidate, $0) }, "\(id) \(candidate.displayString)")
            }
        }
    }
}
