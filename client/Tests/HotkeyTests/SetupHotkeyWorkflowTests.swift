import XCTest
@testable import BasilClient

@MainActor
final class FakeSetupHotkeyStore: SetupHotkeyStoring {
    var table: [String: HotkeyBinding]
    var saved: [[String: HotkeyBinding]] = []
    var loadError: Error?

    init(table: [String: HotkeyBinding] = HotkeyTestSupport.defaultTable()) {
        self.table = table
    }

    func load() async throws -> [String: HotkeyBinding] {
        if let loadError { throw loadError }
        return table
    }

    func save(_ bindings: [String: HotkeyBinding]) async throws {
        saved.append(bindings)
        table = bindings
    }
}

private struct StoreFailure: Error {}

@MainActor
final class SetupHotkeyWorkflowTests: XCTestCase {
    private func workflow(_ store: FakeSetupHotkeyStore, system: HotkeySystemState = HotkeyTestSupport.system()) -> SetupHotkeyWorkflow {
        SetupHotkeyWorkflow(store: store, rows: HotkeyTestSupport.rows, readSystemState: { system })
    }

    private func requested(_ key: String, _ modifiers: [String], doublePressKey: String? = nil) -> HotkeySettingsBindingPayload {
        var raw: [String: Any] = ["key": key, "enabled": true, "modifiers": modifiers, "isDoublePress": doublePressKey != nil]
        raw["doublePressKey"] = doublePressKey ?? NSNull()
        return HotkeySettingsBindingPayload(raw: raw)!
    }

    private func rowPayloads(_ payload: [String: Any]) -> [[String: Any]] {
        payload["rows"] as? [[String: Any]] ?? []
    }

    private func row(_ id: String, in payload: [String: Any]) -> [String: Any]? {
        rowPayloads(payload).first { ($0["id"] as? String) == id }
    }

    // MARK: evaluate

    func testEvaluateListsEveryShownRowWithItsClashAndOneReplacement() async throws {
        let payload = try await workflow(FakeSetupHotkeyStore(), system: HotkeyTestSupport.system(functionKeysAreStandard: false)).evaluate()

        XCTAssertTrue(JSONSerialization.isValidJSONObject(payload))
        XCTAssertEqual(rowPayloads(payload).compactMap { $0["id"] as? String }, HotkeyTestSupport.rows.map(\.id))
        let conversation = try XCTUnwrap(row("conversation_toggle", in: payload))
        XCTAssertEqual((conversation["conflicts"] as? [[String: Any]])?.first?["kind"] as? String, "media_key")
        XCTAssertEqual((conversation["alternative"] as? [String: Any])?["key"] as? String, "C")
        let home = try XCTUnwrap(row("home_board_toggle", in: payload))
        XCTAssertTrue((home["conflicts"] as? [[String: Any]])?.isEmpty == true)
        XCTAssertTrue(home["alternative"] is NSNull)
    }

    func testEvaluateSendsAnAbsentDoublePressKeyAsNull() async throws {
        let payload = try await workflow(FakeSetupHotkeyStore()).evaluate()

        let agent = try XCTUnwrap(row("agent_task", in: payload))
        XCTAssertTrue((agent["binding"] as? [String: Any])?["doublePressKey"] is NSNull)
        let transcribe = try XCTUnwrap(row("transcribe_audio", in: payload))
        XCTAssertEqual((transcribe["binding"] as? [String: Any])?["doublePressKey"] as? String, "command")
    }

    func testEvaluateFailsWithTheNotLoadedSentenceWhenTheTableIsEmptyOrUnreadable() async {
        let empty = FakeSetupHotkeyStore(table: [:])
        do {
            _ = try await workflow(empty).evaluate()
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? SetupHotkeyError, .notLoaded)
        }

        let broken = FakeSetupHotkeyStore()
        broken.loadError = StoreFailure()
        do {
            _ = try await workflow(broken).evaluate()
            XCTFail("expected an error")
        } catch {
            XCTAssertTrue(SetupHotkeyError.message(for: error).contains("Settings, Hotkeys"))
        }
    }

    // MARK: apply

    func testApplySavesFreeKeysKeepsTheDescriptionAndReturnsRefreshedRows() async throws {
        var table = HotkeyTestSupport.defaultTable()
        table["conversation_toggle"] = HotkeyBinding(key: "F8", enabled: true, modifiers: [], hotkeyDescription: "Conversation toggle")
        let store = FakeSetupHotkeyStore(table: table)

        let outcome = try await workflow(store).apply(id: "conversation_toggle", requested: requested("C", ["control", "option"]), acknowledgeConflict: false)

        XCTAssertTrue(outcome.saved)
        XCTAssertTrue(outcome.conflicts.isEmpty)
        XCTAssertEqual(store.saved.count, 1)
        XCTAssertEqual(store.saved[0]["conversation_toggle"]?.key, "C")
        XCTAssertEqual(store.saved[0]["conversation_toggle"]?.modifiers, ["control", "option"])
        XCTAssertEqual(store.saved[0]["conversation_toggle"]?.hotkeyDescription, "Conversation toggle")
        XCTAssertEqual(store.saved[0]["agent_task"]?.key, "Space")
        XCTAssertEqual(store.saved[0].count, table.count)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(outcome.payload))
        XCTAssertEqual(rowPayloads(outcome.payload).count, HotkeyTestSupport.rows.count)
    }

    func testApplyRefusesKeysThatClashUntilTheyAreAcknowledged() async throws {
        let store = FakeSetupHotkeyStore()
        let system = HotkeyTestSupport.system(functionKeysAreStandard: false)

        let refused = try await workflow(store, system: system).apply(id: "conversation_toggle", requested: requested("F8", []), acknowledgeConflict: false)

        XCTAssertFalse(refused.saved)
        XCTAssertEqual(refused.conflicts.map(\.kind), [.mediaKey])
        XCTAssertTrue(store.saved.isEmpty)
        XCTAssertTrue(JSONSerialization.isValidJSONObject(refused.payload))

        let acknowledged = try await workflow(store, system: system).apply(id: "conversation_toggle", requested: requested("F8", []), acknowledgeConflict: true)

        XCTAssertTrue(acknowledged.saved)
        XCTAssertEqual(store.saved.count, 1)
    }

    func testApplyCheckOnlyReportsFreeKeysWithoutSavingAndStillRefusesClashes() async throws {
        let store = FakeSetupHotkeyStore()
        let system = HotkeyTestSupport.system(functionKeysAreStandard: false)

        let free = try await workflow(store, system: system).apply(id: "conversation_toggle", requested: requested("C", ["control", "option"]), acknowledgeConflict: false, checkOnly: true)
        XCTAssertTrue(free.saved)
        XCTAssertTrue(free.conflicts.isEmpty)
        XCTAssertTrue(store.saved.isEmpty)

        let clash = try await workflow(store, system: system).apply(id: "conversation_toggle", requested: requested("F8", []), acknowledgeConflict: false, checkOnly: true)
        XCTAssertFalse(clash.saved)
        XCTAssertEqual(clash.conflicts.map(\.kind), [.mediaKey])
        XCTAssertTrue(store.saved.isEmpty)
    }

    func testApplyRefusesKeysAnotherBasilRowUses() async throws {
        let store = FakeSetupHotkeyStore()

        let outcome = try await workflow(store).apply(id: "conversation_toggle", requested: requested("B", ["control", "option"]), acknowledgeConflict: false)

        XCTAssertFalse(outcome.saved)
        XCTAssertEqual(outcome.conflicts.map(\.kind), [.basilDuplicate])
        XCTAssertTrue(store.saved.isEmpty)
    }

    func testApplyRejectsAPlainKeyWithNoModifierEvenWhenAcknowledged() async {
        let store = FakeSetupHotkeyStore()
        do {
            _ = try await workflow(store).apply(id: "conversation_toggle", requested: requested("A", []), acknowledgeConflict: true)
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? SetupHotkeyError, .needsModifier)
        }
        XCTAssertTrue(store.saved.isEmpty)
    }

    func testApplyAcceptsAFunctionKeyWithNoModifierAndADoublePress() async throws {
        let store = FakeSetupHotkeyStore()

        let functionKey = try await workflow(store).apply(id: "conversation_toggle", requested: requested("F6", []), acknowledgeConflict: false)
        let doublePress = try await workflow(store).apply(id: "assistant_session", requested: requested("", [], doublePressKey: "control"), acknowledgeConflict: false)

        XCTAssertTrue(functionKey.saved)
        XCTAssertTrue(doublePress.saved)
        XCTAssertEqual(store.saved.last?["assistant_session"]?.isDoublePress, true)
        XCTAssertEqual(store.saved.last?["assistant_session"]?.doublePressKey, "control")
    }

    func testApplyRejectsAnUnknownRowAnAbsentRowAndAnEmptyKey() async {
        let store = FakeSetupHotkeyStore()
        for id in ["capture_screen", "not_a_row"] {
            do {
                _ = try await workflow(store).apply(id: id, requested: requested("C", ["control"]), acknowledgeConflict: false)
                XCTFail("expected an error for \(id)")
            } catch {
                XCTAssertEqual(error as? SetupHotkeyError, .unknownHotkey)
            }
        }
        do {
            _ = try await workflow(store).apply(id: "conversation_toggle", requested: requested("  ", ["control"]), acknowledgeConflict: false)
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? SetupHotkeyError, .emptyKey)
        }
        XCTAssertTrue(store.saved.isEmpty)
    }

    // MARK: resolve

    func testResolveSwitchesEveryClashingRowInOneSaveAndKeepsEverythingElse() async throws {
        var table = HotkeyTestSupport.defaultTable()
        table["conversation_toggle"] = HotkeyBinding(key: "F8", enabled: true, modifiers: [], hotkeyDescription: "Conversation toggle")
        let store = FakeSetupHotkeyStore(table: table)

        let outcome = try await workflow(store, system: HotkeyTestSupport.system(functionKeysAreStandard: false)).resolveConflicts()

        XCTAssertEqual(outcome.changes.map(\.id), ["conversation_toggle"])
        XCTAssertEqual(outcome.changes.first?.reason, "this Mac's media keys")
        XCTAssertEqual(outcome.changes.first?.from.key, "F8")
        XCTAssertEqual(outcome.changes.first?.to.key, "C")
        XCTAssertTrue(outcome.unresolved.isEmpty)
        XCTAssertEqual(store.saved.count, 1)
        XCTAssertEqual(store.saved[0]["conversation_toggle"]?.key, "C")
        XCTAssertEqual(store.saved[0]["conversation_toggle"]?.hotkeyDescription, "Conversation toggle")
        XCTAssertEqual(store.saved[0]["transcribe_audio"]?.doublePressKey, "command")
        XCTAssertEqual(store.saved[0]["capture_screen"]?.key, "F1")
        XCTAssertTrue(JSONSerialization.isValidJSONObject(outcome.payload))
    }

    func testResolveLeavesAClashingRowTheCallerAlreadyDecidedOn() async throws {
        var table = HotkeyTestSupport.defaultTable()
        table["conversation_toggle"] = HotkeyBinding(key: "F8", enabled: true, modifiers: [], hotkeyDescription: "Conversation toggle")
        let store = FakeSetupHotkeyStore(table: table)

        let outcome = try await workflow(store, system: HotkeyTestSupport.system(functionKeysAreStandard: false)).resolveConflicts(excluding: ["conversation_toggle"])

        XCTAssertTrue(outcome.changes.isEmpty)
        XCTAssertTrue(outcome.unresolved.isEmpty)
        XCTAssertTrue(store.saved.isEmpty)
        XCTAssertEqual(store.table["conversation_toggle"]?.key, "F8")
    }

    func testResolveSavesNothingWhenThereIsNoClash() async throws {
        let store = FakeSetupHotkeyStore()

        let outcome = try await workflow(store).resolveConflicts()

        XCTAssertTrue(outcome.changes.isEmpty)
        XCTAssertTrue(outcome.unresolved.isEmpty)
        XCTAssertTrue(store.saved.isEmpty)
    }

    func testResolveReportsARowWithNoSafeReplacementAndStillFixesTheOthers() async throws {
        var table = HotkeyTestSupport.defaultTable()
        table["insert_assistant_output"] = HotkeyTestSupport.doublePress("control")
        table["streaming_transcription"] = HotkeyTestSupport.doublePress("shift")
        let store = FakeSetupHotkeyStore(table: table)

        let outcome = try await workflow(store, system: HotkeyTestSupport.system(siri: HotkeyTestSupport.unreadableSiri)).resolveConflicts()

        XCTAssertEqual(outcome.changes.map(\.id), ["agent_task"])
        XCTAssertEqual(outcome.changes.first?.to.modifiers, ["option", "shift"])
        XCTAssertEqual(outcome.changes.first?.reason, "Siri")
        XCTAssertEqual(outcome.unresolved.map(\.id), ["transcribe_audio", "assistant_session"])
        XCTAssertTrue(outcome.unresolved.allSatisfy { !$0.message.isEmpty })
        XCTAssertEqual(store.saved.count, 1)
        XCTAssertEqual(store.saved[0]["transcribe_audio"]?.doublePressKey, "command")
        XCTAssertEqual(store.saved[0]["assistant_session"]?.doublePressKey, "option")
        XCTAssertTrue(JSONSerialization.isValidJSONObject(outcome.payload))
    }

    func testResolveSavesNothingWhenNoRowCanBeFixed() async throws {
        var table = HotkeyTestSupport.defaultTable()
        table["agent_task"] = HotkeyTestSupport.chord("B", ["control", "option"])
        table["home_board_toggle"] = HotkeyTestSupport.chord("B", ["control", "option"])
        table["capture_screen"] = HotkeyTestSupport.chord("H", ["control", "option"])
        table["streaming_transcription"] = HotkeyTestSupport.chord("B", ["control", "option", "shift"])
        table["insert_assistant_output"] = HotkeyTestSupport.chord("J", ["control", "option"])
        let store = FakeSetupHotkeyStore(table: table)

        let outcome = try await workflow(store).resolveConflicts()

        XCTAssertEqual(outcome.changes.map(\.id), [])
        XCTAssertEqual(outcome.unresolved.map(\.id), ["home_board_toggle"])
        XCTAssertTrue(store.saved.isEmpty)
    }

    // MARK: validation and errors

    func testValidationAcceptsSafeKeysAndRejectsUnsafeOnes() {
        XCTAssertNoThrow(try SetupHotkeyPayload.validate(HotkeyTestSupport.chord("B", ["control", "option"])))
        XCTAssertNoThrow(try SetupHotkeyPayload.validate(HotkeyTestSupport.chord("F8", [])))
        XCTAssertNoThrow(try SetupHotkeyPayload.validate(HotkeyTestSupport.doublePress("cmd")))
        XCTAssertThrowsError(try SetupHotkeyPayload.validate(HotkeyTestSupport.chord("B", []))) {
            XCTAssertEqual($0 as? SetupHotkeyError, .needsModifier)
        }
        XCTAssertThrowsError(try SetupHotkeyPayload.validate(HotkeyTestSupport.chord("", ["control"]))) {
            XCTAssertEqual($0 as? SetupHotkeyError, .emptyKey)
        }
        XCTAssertThrowsError(try SetupHotkeyPayload.validate(HotkeyTestSupport.doublePress("hyper"))) {
            XCTAssertEqual($0 as? SetupHotkeyError, .invalidDoublePress)
        }
    }

    func testEveryErrorHasAFullSentenceInTheSetupVoiceAndUnknownErrorsGetTheGenericOne() {
        for error in [SetupHotkeyError.unknownHotkey, .notLoaded, .emptyKey, .invalidDoublePress, .needsModifier] {
            let sentence = SetupHotkeyError.message(for: error)
            XCTAssertTrue(sentence.hasSuffix("."), sentence)
            XCTAssertFalse(sentence.contains("SetupHotkeyError"), sentence)
        }
        XCTAssertEqual(
            SetupHotkeyError.message(for: StoreFailure()),
            "I couldn't read or save your hotkeys just now. You can change them in Settings, Hotkeys."
        )
    }
}
