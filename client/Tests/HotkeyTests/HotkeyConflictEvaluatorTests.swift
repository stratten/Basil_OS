import XCTest
@testable import BasilClient

final class HotkeyConflictEvaluatorTests: XCTestCase {
    private let rows = HotkeyTestSupport.rows

    private func conflicts(
        _ table: [String: HotkeyBinding]? = nil,
        system: HotkeySystemState = HotkeyTestSupport.system()
    ) -> [HotkeyConflict] {
        HotkeyConflictEvaluator.conflicts(bindings: table ?? HotkeyTestSupport.defaultTable(), rows: rows, system: system)
    }

    func testKeyCodesAreCaseInsensitiveAndUnknownKeysHaveNone() {
        XCTAssertEqual(HotkeyKeyCodes.code(for: "b"), 11)
        XCTAssertEqual(HotkeyKeyCodes.code(for: "SPACE"), 49)
        XCTAssertEqual(HotkeyKeyCodes.code(for: "space"), 49)
        XCTAssertEqual(HotkeyKeyCodes.code(for: "f8"), 100)
        XCTAssertNil(HotkeyKeyCodes.code(for: "↩"))
        XCTAssertTrue(HotkeyKeyCodes.isFunctionKey("f12"))
        XCTAssertFalse(HotkeyKeyCodes.isFunctionKey("B"))
    }

    func testNothingIsReportedForTheDefaultsWhenFunctionKeysAreStandardAndNothingIsOn() {
        XCTAssertTrue(conflicts().isEmpty)
    }

    func testTheDefaultF8IsAPossibleMediaKeyClashWhenFunctionKeysAreNotStandard() {
        let found = conflicts(system: HotkeyTestSupport.system(functionKeysAreStandard: false))

        XCTAssertEqual(found.map(\.hotkeyId), ["conversation_toggle"])
        XCTAssertEqual(found.first?.kind, .mediaKey)
        XCTAssertEqual(found.first?.certainty, .possible)
        XCTAssertEqual(found.first?.source, "this Mac's media keys")
        XCTAssertTrue(found.first?.message.contains("F8") == true)
        XCTAssertTrue(found.first?.message.contains("fn") == true)
    }

    func testAModifierDoesNotMakeAFunctionKeySafeFromTheMediaKeyRule() {
        var table = HotkeyTestSupport.defaultTable()
        table["conversation_toggle"] = HotkeyTestSupport.chord("F8", ["option"])

        let found = conflicts(table, system: HotkeyTestSupport.system(functionKeysAreStandard: false))

        XCTAssertEqual(found.map(\.kind), [.mediaKey])
    }

    func testAnEnabledMacShortcutOnALetterKeyIsAnExactClash() {
        var table = HotkeyTestSupport.defaultTable()
        table["home_board_toggle"] = HotkeyTestSupport.chord("1", ["control"])
        let system = HotkeyTestSupport.system(symbolic: HotkeyTestSupport.symbolic("118", keyCode: 18, mask: 262_144))

        let found = conflicts(table, system: system)

        XCTAssertEqual(found.map(\.hotkeyId), ["home_board_toggle"])
        XCTAssertEqual(found.first?.kind, .macShortcut)
        XCTAssertEqual(found.first?.certainty, .exact)
        XCTAssertEqual(found.first?.source, "the macOS shortcut that switches to Desktop 1")
        XCTAssertTrue(found.first?.message.contains("System Settings, Keyboard, Keyboard Shortcuts") == true)
    }

    func testACustomizedDictationShortcutOnALetterKeyIsNamedAsDictation() {
        var table = HotkeyTestSupport.defaultTable()
        table["home_board_toggle"] = HotkeyTestSupport.chord("D", ["control"])
        let system = HotkeyTestSupport.system(symbolic: HotkeyTestSupport.symbolic("164", keyCode: 2, mask: 262_144))

        let found = conflicts(table, system: system)

        XCTAssertEqual(found.map(\.hotkeyId), ["home_board_toggle"])
        XCTAssertEqual(found.first?.source, "the macOS Dictation shortcut")
        XCTAssertEqual(found.first?.certainty, .exact)
    }

    func testADictationShortcutOnTheDefaultDoublePressModifierIsReportedOnceAsPossible() {
        let symbolic: [String: Any] = ["164": ["enabled": 1, "value": ["type": "modifier", "parameters": [524_288, 4_286_578_687]]]]

        let found = conflicts(HotkeyTestSupport.defaultTable(), system: HotkeyTestSupport.system(symbolic: symbolic))

        XCTAssertEqual(found.map(\.hotkeyId), ["assistant_session"])
        XCTAssertEqual(found.first?.kind, .macShortcut)
        XCTAssertEqual(found.first?.certainty, .possible)
        XCTAssertEqual(found.first?.source, "the macOS Dictation shortcut")
    }

    func testAnUnnamedMacShortcutStillGetsAReadableSource() {
        var table = HotkeyTestSupport.defaultTable()
        table["home_board_toggle"] = HotkeyTestSupport.chord("B", ["control"])
        let system = HotkeyTestSupport.system(symbolic: HotkeyTestSupport.symbolic("999", keyCode: 11, mask: 262_144))

        XCTAssertEqual(conflicts(table, system: system).first?.source, "a macOS keyboard shortcut")
    }

    func testADisabledMacShortcutAndADifferentModifierMaskAreIgnored() {
        var table = HotkeyTestSupport.defaultTable()
        table["home_board_toggle"] = HotkeyTestSupport.chord("1", ["control", "option"])

        XCTAssertTrue(conflicts(table, system: HotkeyTestSupport.system(symbolic: HotkeyTestSupport.symbolic("118", keyCode: 18, mask: 262_144))).isEmpty)

        table["home_board_toggle"] = HotkeyTestSupport.chord("1", ["control"])
        XCTAssertTrue(conflicts(table, system: HotkeyTestSupport.system(symbolic: HotkeyTestSupport.symbolic("118", keyCode: 18, mask: 262_144, enabled: false))).isEmpty)
    }

    func testSpaceBindingsStayWithTheExistingDetectorAndAreNotReportedTwice() {
        let system = HotkeyTestSupport.system(symbolic: HotkeyTestSupport.symbolic("64", keyCode: 49, mask: 524_288))

        let found = conflicts(system: system)

        XCTAssertEqual(found.map(\.hotkeyId), ["agent_task"])
        XCTAssertEqual(found.first?.source, "Spotlight")
        XCTAssertEqual(found.first?.kind, .macShortcut)
    }

    func testTheSiriPossibleClashIsCarriedThrough() {
        let found = conflicts(system: HotkeyTestSupport.system(siri: HotkeyTestSupport.unreadableSiri))

        XCTAssertEqual(Set(found.map(\.hotkeyId)), ["transcribe_audio", "assistant_session", "agent_task"])
        XCTAssertTrue(found.allSatisfy { $0.source == "Siri" && $0.certainty == .possible })
    }

    func testTwoBasilBindingsOnTheSameKeysFlagOnlyTheLaterRow() {
        var table = HotkeyTestSupport.defaultTable()
        table["assistant_session"] = HotkeyTestSupport.doublePress("command")

        let found = conflicts(table)

        XCTAssertEqual(found.map(\.hotkeyId), ["assistant_session"])
        XCTAssertEqual(found.first?.kind, .basilDuplicate)
        XCTAssertEqual(found.first?.certainty, .exact)
        XCTAssertEqual(found.first?.source, HotkeyTestSupport.title("transcribe_audio"))
    }

    func testAHiddenBindingKeepsItsKeysAndTheShownRowYields() {
        var table = HotkeyTestSupport.defaultTable()
        table["conversation_toggle"] = HotkeyTestSupport.chord("F5", [])

        let found = conflicts(table)

        XCTAssertEqual(found.map(\.hotkeyId), ["conversation_toggle"])
        XCTAssertEqual(found.first?.kind, .basilDuplicate)
        XCTAssertEqual(found.first?.source, "another Basil shortcut")
    }

    func testAliasedModifiersAreTheSameKeys() {
        XCTAssertTrue(HotkeyConflictEvaluator.collides(
            HotkeyTestSupport.chord("B", ["alt", "ctrl"]),
            HotkeyTestSupport.chord("b", ["control", "option"])
        ))
    }

    func testDisabledBindingsAndMismatchedDoublePressesNeverCollide() {
        let off = HotkeyBinding(key: "B", enabled: false, modifiers: ["control"])
        XCTAssertFalse(HotkeyConflictEvaluator.collides(off, HotkeyTestSupport.chord("B", ["control"])))
        XCTAssertFalse(HotkeyConflictEvaluator.collides(HotkeyTestSupport.doublePress("command"), HotkeyTestSupport.doublePress("option")))
        XCTAssertFalse(HotkeyConflictEvaluator.collides(HotkeyTestSupport.doublePress("command"), HotkeyTestSupport.chord("B", ["command"])))
        XCTAssertTrue(HotkeyConflictEvaluator.collides(HotkeyTestSupport.doublePress("cmd"), HotkeyTestSupport.doublePress("command")))
    }

    func testAProposalIsCheckedAgainstEveryOtherBindingWhateverTheirOrder() {
        let found = HotkeyConflictEvaluator.conflicts(
            replacing: "transcribe_audio",
            with: HotkeyTestSupport.doublePress("option"),
            in: HotkeyTestSupport.defaultTable(),
            rows: rows,
            system: HotkeyTestSupport.system()
        )

        XCTAssertEqual(found.map(\.kind), [.basilDuplicate])
        XCTAssertEqual(found.first?.source, HotkeyTestSupport.title("assistant_session"))
    }

    func testAProposalThatIsFreeHasNoConflicts() {
        XCTAssertTrue(HotkeyConflictEvaluator.conflicts(
            replacing: "conversation_toggle",
            with: HotkeyTestSupport.chord("C", ["control", "option"]),
            in: HotkeyTestSupport.defaultTable(),
            rows: rows,
            system: HotkeyTestSupport.system(functionKeysAreStandard: false)
        ).isEmpty)
    }

    func testResultsComeBackInRowOrder() {
        var table = HotkeyTestSupport.defaultTable()
        table["home_board_toggle"] = HotkeyTestSupport.chord("1", ["control"])
        let system = HotkeyTestSupport.system(
            functionKeysAreStandard: false,
            symbolic: HotkeyTestSupport.symbolic("118", keyCode: 18, mask: 262_144)
        )

        XCTAssertEqual(conflicts(table, system: system).map(\.hotkeyId), ["conversation_toggle", "home_board_toggle"])
    }

    func testThePayloadCarriesEveryFieldThePageShows() {
        let payload = HotkeyConflict(
            hotkeyId: "agent_task",
            kind: .mediaKey,
            source: "this Mac's media keys",
            certainty: .possible,
            message: "A sentence."
        ).payload

        XCTAssertEqual(payload["hotkeyId"] as? String, "agent_task")
        XCTAssertEqual(payload["kind"] as? String, "media_key")
        XCTAssertEqual(payload["certainty"] as? String, "possible")
        XCTAssertEqual(payload["source"] as? String, "this Mac's media keys")
        XCTAssertEqual(payload["message"] as? String, "A sentence.")
    }
}
