import XCTest
@testable import BasilClient

final class SystemShortcutConflictDetectorTests: XCTestCase {
    private let rows = HotkeyRowCatalog.rows

    private var defaults: [String: HotkeyBinding] {
        Dictionary(uniqueKeysWithValues: rows.map { ($0.id, HotkeyRowCatalog.defaultBinding(for: $0.id)) })
    }

    private func symbolic(_ identifier: String, mask: Int, enabled: Bool = true, keyCode: Int = 49) -> [String: Any] {
        [identifier: ["enabled": enabled ? 1 : 0, "value": ["type": "standard", "parameters": [32, keyCode, mask]]]]
    }

    /// Runs the detector as macOS 27 unless a version is given, so a result never depends on the Mac running the tests.
    private func detect(symbolicHotKeys: [String: Any]? = nil, siri: [String: Any]? = nil, bindings: [String: HotkeyBinding]? = nil, macOS: Int = 27) -> [SystemShortcutConflict] {
        SystemShortcutConflictDetector.conflicts(bindings: bindings ?? defaults, rows: rows, symbolicHotKeys: symbolicHotKeys, siriPreferences: siri, macOSMajorVersion: macOS)
    }

    func testNothingIsReportedWhenNoSystemShortcutIsOn() {
        XCTAssertTrue(detect().isEmpty)
        XCTAssertTrue(detect(symbolicHotKeys: symbolic("64", mask: 1_048_576, enabled: false)).isEmpty)
    }

    func testDefaultBindingsDoNotCollideWithStockSpotlightShortcuts() {
        let stock = symbolic("64", mask: 1_048_576).merging(symbolic("65", mask: 1_572_864)) { first, _ in first }
        XCTAssertTrue(detect(symbolicHotKeys: stock).isEmpty)
    }

    func testOptionSpaceIsAnExactConflictWithAnEnabledSpotlightShortcutOnOptionSpace() {
        let conflicts = detect(symbolicHotKeys: symbolic("64", mask: 524_288))

        XCTAssertEqual(conflicts.map(\.hotkeyId), ["agent_task"])
        XCTAssertEqual(conflicts.first?.source, "Spotlight")
        XCTAssertEqual(conflicts.first?.certainty, .exact)
        XCTAssertTrue(conflicts.first?.message.contains("⌥␣") == true)
    }

    func testADisabledBindingNeverConflicts() {
        var bindings = defaults
        bindings["agent_task"] = HotkeyBinding(key: "Space", enabled: false, modifiers: ["option"])

        XCTAssertTrue(detect(symbolicHotKeys: symbolic("64", mask: 524_288), bindings: bindings).isEmpty)
    }

    func testAStandardSiriShortcutOnOptionSpaceIsAnExactConflict() {
        let siri: [String: Any] = ["KeyboardShortcutSAE": ["enabled": 1, "value": ["type": "standard", "parameters": [32, 49, 524_288]]]]
        let conflicts = detect(siri: siri)

        XCTAssertEqual(conflicts.map(\.hotkeyId), ["agent_task"])
        XCTAssertEqual(conflicts.first?.source, "Siri")
        XCTAssertEqual(conflicts.first?.certainty, .exact)
    }

    func testAnUnreadableSiriShortcutIsAPossibleConflictForDoubledCommandAndOptionSpaceButNotDoubledOption() {
        let siri: [String: Any] = ["KeyboardShortcutSAE": ["enabled": 1, "value": ["type": "SAE1.0"]]]
        let conflicts = detect(siri: siri)

        XCTAssertEqual(Set(conflicts.map(\.hotkeyId)), ["transcribe_audio", "agent_task"])
        XCTAssertFalse(conflicts.contains { $0.hotkeyId == "assistant_session" })
        XCTAssertTrue(conflicts.allSatisfy { $0.certainty == .possible && $0.source == "Siri" })
    }

    func testAMacWithNoSiriShortcutPreferenceHasTheDoubledCommandDefaultOnMacOS15And26() {
        for version in [15, 26] {
            let conflicts = detect(siri: nil, macOS: version)

            XCTAssertEqual(conflicts.map(\.hotkeyId), ["transcribe_audio"], "macOS \(version)")
            XCTAssertEqual(conflicts.first?.source, "Siri")
            XCTAssertEqual(conflicts.first?.certainty, .possible)
            XCTAssertTrue(conflicts.first?.message.contains("on by default") == true)
        }
    }

    func testTheSiriDefaultDoesNotApplyBeforeMacOS15OrFromMacOS27() {
        XCTAssertTrue(detect(siri: nil, macOS: 14).isEmpty)
        XCTAssertTrue(detect(siri: nil, macOS: 27).isEmpty)
    }

    func testTheSiriDefaultIsNotAssumedWhenSiriIsOffOrTheShortcutHasAStoredValue() {
        XCTAssertTrue(detect(siri: ["AssistantEnabled": 0], macOS: 26).isEmpty)
        XCTAssertEqual(detect(siri: ["AssistantEnabled": 1], macOS: 26).map(\.hotkeyId), ["transcribe_audio"])
        XCTAssertTrue(detect(siri: ["KeyboardShortcutSAE": ["enabled": 0, "value": ["type": "SAE1.0"]]], macOS: 26).isEmpty)
        XCTAssertTrue(detect(siri: ["KeyboardShortcutPreSAE": ["enabled": 0]], macOS: 26).isEmpty)
    }

    func testTheSiriDefaultOnlyAppliesToADoubledCommandHotkey() {
        var bindings = defaults
        bindings["transcribe_audio"] = HotkeyBinding(key: "", enabled: true, modifiers: [], isDoublePress: true, doublePressKey: "control")
        XCTAssertTrue(detect(siri: nil, bindings: bindings, macOS: 26).isEmpty)

        bindings["transcribe_audio"] = HotkeyBinding(key: "", enabled: false, modifiers: [], isDoublePress: true, doublePressKey: "command")
        XCTAssertTrue(detect(siri: nil, bindings: bindings, macOS: 26).isEmpty)
    }

    func testASiriShortcutThatIsTurnedOffReportsNothing() {
        let siri: [String: Any] = ["KeyboardShortcutSAE": ["enabled": 0, "value": ["type": "SAE1.0"]]]

        XCTAssertTrue(detect(siri: siri).isEmpty)
    }

    private func dictationModifier(_ mask: Int, enabled: Bool = true) -> [String: Any] {
        ["164": ["enabled": enabled ? 1 : 0, "value": ["type": "modifier", "parameters": [mask, 4_286_578_687]]]]
    }

    func testADictationShortcutOnTheSameModifierAsADoublePressHotkeyIsAPossibleConflict() {
        let conflicts = detect(symbolicHotKeys: dictationModifier(1_048_576))

        XCTAssertEqual(conflicts.map(\.hotkeyId), ["transcribe_audio"])
        XCTAssertEqual(conflicts.first?.source, "the macOS Dictation shortcut")
        XCTAssertEqual(conflicts.first?.certainty, .possible)
        XCTAssertTrue(conflicts.first?.message.contains("System Settings, Keyboard, Dictation") == true)
    }

    func testADictationShortcutLimitedToTheLeftOrRightCommandKeyIsStillAPossibleConflict() {
        for stored in [1_048_584, 1_048_592] {
            let conflicts = detect(symbolicHotKeys: dictationModifier(stored))

            XCTAssertEqual(conflicts.map(\.hotkeyId), ["transcribe_audio"], "stored value \(stored)")
            XCTAssertEqual(conflicts.first?.certainty, .possible)
        }
    }

    func testADictationShortcutOnAnotherModifierDisabledOrOnFnReportsNothing() {
        XCTAssertTrue(detect(symbolicHotKeys: dictationModifier(262_144)).isEmpty)
        XCTAssertTrue(detect(symbolicHotKeys: dictationModifier(8_388_608)).isEmpty)
        XCTAssertTrue(detect(symbolicHotKeys: dictationModifier(1_048_576, enabled: false)).isEmpty)
    }

    func testACustomizedDictationShortcutOnOptionSpaceIsAnExactConflict() {
        let conflicts = detect(symbolicHotKeys: symbolic("164", mask: 524_288))

        XCTAssertEqual(conflicts.map(\.hotkeyId), ["agent_task"])
        XCTAssertEqual(conflicts.first?.source, "the macOS Dictation shortcut")
        XCTAssertEqual(conflicts.first?.certainty, .exact)
    }

    func testADisabledDoublePressHotkeyNeverConflictsWithDictation() {
        var bindings = defaults
        bindings["transcribe_audio"] = HotkeyBinding(key: "", enabled: false, modifiers: [], isDoublePress: true, doublePressKey: "command")

        XCTAssertTrue(detect(symbolicHotKeys: dictationModifier(1_048_576), bindings: bindings).isEmpty)
    }

    func testPayloadCarriesEverythingTheWebPagesNeed() {
        let conflict = SystemShortcutConflict(hotkeyId: "agent_task", source: "Siri", certainty: .possible, message: "m")

        XCTAssertEqual(conflict.payload["hotkeyId"] as? String, "agent_task")
        XCTAssertEqual(conflict.payload["source"] as? String, "Siri")
        XCTAssertEqual(conflict.payload["certainty"] as? String, "possible")
        XCTAssertEqual(conflict.payload["message"] as? String, "m")
    }
}
