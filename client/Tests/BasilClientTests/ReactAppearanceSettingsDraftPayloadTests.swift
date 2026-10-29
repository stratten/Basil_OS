import XCTest
@testable import BasilClient

final class ReactAppearanceSettingsDraftPayloadTests: XCTestCase {
    private func validRawDraft(overrides: [String: Any] = [:]) -> [String: Any] {
        var raw: [String: Any] = [
            "backgroundColorRed": 1.0,
            "backgroundColorGreen": 1.0,
            "backgroundColorBlue": 1.0,
            "primaryColorRed": 0.0,
            "primaryColorGreen": 0.188,
            "primaryColorBlue": 0.529,
            "secondaryColorRed": 0.2,
            "secondaryColorGreen": 0.333,
            "secondaryColorBlue": 0.608,
            "textColorRed": 0.0,
            "textColorGreen": 0.0,
            "textColorBlue": 0.0,
            "processingColorRed": 0.486,
            "processingColorGreen": 0.227,
            "processingColorBlue": 0.929,
            "processingAccentColorRed": 0.867,
            "processingAccentColorGreen": 0.839,
            "processingAccentColorBlue": 0.996,
            "preferredFont": "Helvetica-Light",
        ]
        for (key, value) in overrides {
            raw[key] = value
        }
        return raw
    }

    private func validRawColorPickerRequest(overrides: [String: Any] = [:]) -> [String: Any] {
        var raw: [String: Any] = [
            "fieldId": "primary",
            "red": 0.0,
            "green": 0.188,
            "blue": 0.529,
        ]
        for (key, value) in overrides {
            raw[key] = value
        }
        return raw
    }

    func testValidDraftParsesEveryField() throws {
        let payload = try XCTUnwrap(ReactAppearanceSettingsDraftPayload(raw: validRawDraft()))
        XCTAssertEqual(payload.primaryColorGreen, 0.188)
        XCTAssertEqual(payload.preferredFont, "Helvetica-Light")
        XCTAssertEqual(payload.processingAccentColorBlue, 0.996)
    }

    func testMissingRequiredFieldReturnsNil() {
        var raw = validRawDraft()
        raw.removeValue(forKey: "primaryColorRed")
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: raw))
    }

    func testColorValueAboveOneReturnsNil() {
        let raw = validRawDraft(overrides: ["primaryColorRed": 1.5])
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: raw))
    }

    func testColorValueBelowZeroReturnsNil() {
        let raw = validRawDraft(overrides: ["textColorBlue": -0.1])
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: raw))
    }

    func testEmptyPreferredFontReturnsNil() {
        let raw = validRawDraft(overrides: ["preferredFont": ""])
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: raw))
    }

    func testNonNumericColorFieldReturnsNil() {
        let raw = validRawDraft(overrides: ["primaryColorRed": "not-a-number"])
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: raw))
    }

    func testToAppearanceSettingsPreservesAllEighteenChannelsAndFont() throws {
        let payload = try XCTUnwrap(ReactAppearanceSettingsDraftPayload(raw: validRawDraft()))
        let settings = payload.toAppearanceSettings()
        XCTAssertEqual(settings.backgroundColorRed, 1.0)
        XCTAssertEqual(settings.secondaryColorBlue, 0.608)
        XCTAssertEqual(settings.processingColorGreen, 0.227)
        XCTAssertEqual(settings.processingAccentColorRed, 0.867)
        XCTAssertEqual(settings.preferredFont, "Helvetica-Light")
    }

    func testColorPickerRequestAcceptsEveryAllowListedField() {
        for field in ["background", "primary", "secondary", "text"] {
            XCTAssertEqual(
                ReactAppearanceColorPickerRequest(raw: validRawColorPickerRequest(overrides: ["fieldId": field]))?.field.rawValue,
                field
            )
        }
    }

    func testColorPickerRequestRejectsMalformedOrOutOfRangeValues() {
        XCTAssertNil(ReactAppearanceColorPickerRequest(raw: validRawColorPickerRequest(overrides: ["fieldId": "unknown"])))
        XCTAssertNil(ReactAppearanceColorPickerRequest(raw: validRawColorPickerRequest(overrides: ["red": "not-a-number"])))
        XCTAssertNil(ReactAppearanceColorPickerRequest(raw: validRawColorPickerRequest(overrides: ["green": Double.nan])))
        XCTAssertNil(ReactAppearanceColorPickerRequest(raw: validRawColorPickerRequest(overrides: ["blue": -0.1])))
        XCTAssertNil(ReactAppearanceColorPickerRequest(raw: validRawColorPickerRequest(overrides: ["red": 1.1])))
    }

    func testDraftWithoutSurfaceFinishDefaultsToBackgroundOnlyMetallic() throws {
        let payload = try XCTUnwrap(ReactAppearanceSettingsDraftPayload(raw: validRawDraft()))

        XCTAssertEqual(payload.surfaceFinish, "metal_backdrop")
        XCTAssertEqual(payload.toAppearanceSettings().surfaceFinish, "metal_backdrop")
    }

    func testShippedDefaultAndResetUseBackgroundOnlyMetallic() throws {
        XCTAssertEqual(AppearanceSettings().surfaceFinish, "metal_backdrop")

        let decodedWithoutFinish = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"preferred_font":"Helvetica-Light"}"#.utf8))
        XCTAssertEqual(decodedWithoutFinish.surfaceFinish, "metal_backdrop")

        let decodedFlat = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"preferred_font":"Helvetica-Light","surface_finish":"flat"}"#.utf8))
        XCTAssertEqual(decodedFlat.surfaceFinish, "flat")
    }

    func testDraftAcceptsMetalSurfaceFinish() throws {
        let payload = try XCTUnwrap(
            ReactAppearanceSettingsDraftPayload(raw: validRawDraft(overrides: ["surfaceFinish": "metal"]))
        )

        XCTAssertEqual(payload.surfaceFinish, "metal")
        XCTAssertEqual(payload.toAppearanceSettings().surfaceFinish, "metal")
    }

    func testDraftAcceptsMetalBackdropSurfaceFinish() throws {
        let payload = try XCTUnwrap(
            ReactAppearanceSettingsDraftPayload(raw: validRawDraft(overrides: ["surfaceFinish": "metal_backdrop"]))
        )

        XCTAssertEqual(payload.surfaceFinish, "metal_backdrop")
        XCTAssertEqual(payload.toAppearanceSettings().surfaceFinish, "metal_backdrop")
    }

    func testDraftRejectsUnknownSurfaceFinish() {
        XCTAssertNil(
            ReactAppearanceSettingsDraftPayload(raw: validRawDraft(overrides: ["surfaceFinish": "chrome"]))
        )
    }
    func testDraftWithoutBlueprintRevealDefaultsToOn() throws {
        let payload = try XCTUnwrap(ReactAppearanceSettingsDraftPayload(raw: validRawDraft()))

        XCTAssertTrue(payload.blueprintReveal)
        XCTAssertTrue(payload.toAppearanceSettings().blueprintReveal)
    }

    func testDraftCarriesBlueprintRevealIntoAppearanceSettings() throws {
        let payload = try XCTUnwrap(
            ReactAppearanceSettingsDraftPayload(raw: validRawDraft(overrides: ["blueprintReveal": true]))
        )

        XCTAssertTrue(payload.blueprintReveal)
        XCTAssertTrue(payload.toAppearanceSettings().blueprintReveal)
    }

    func testDraftRejectsNonBooleanBlueprintReveal() {
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: validRawDraft(overrides: ["blueprintReveal": "yes"])))
    }

    func testBlueprintRevealIsOnByDefaultAndDecodesAndEncodesAsSnakeCase() throws {
        XCTAssertTrue(AppearanceSettings().blueprintReveal)

        let decodedWithoutField = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"preferred_font":"Helvetica-Light"}"#.utf8))
        XCTAssertTrue(decodedWithoutField.blueprintReveal)

        let decodedOff = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"preferred_font":"Helvetica-Light","blueprint_reveal":false}"#.utf8))
        XCTAssertFalse(decodedOff.blueprintReveal)

        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(decodedOff)) as? [String: Any]
        XCTAssertEqual(encoded?["blueprint_reveal"] as? Bool, false)
    }

    @MainActor
    func testAestheticSystemFollowsLoadedBlueprintRevealSetting() {
        AestheticSystem.loadFromSettings(AppearanceSettings(blueprintReveal: false))
        XCTAssertFalse(AestheticSystem.blueprintReveal)

        AestheticSystem.loadFromSettings(AppearanceSettings())
        XCTAssertTrue(AestheticSystem.blueprintReveal)
    }

    func testDraftWithoutChainExpansionDefaultsToSingle() throws {
        let payload = try XCTUnwrap(ReactAppearanceSettingsDraftPayload(raw: validRawDraft()))

        XCTAssertEqual(payload.agentTaskChainExpansion, "single")
        XCTAssertEqual(payload.toAppearanceSettings().agentTaskChainExpansion, "single")
    }

    func testDraftCarriesChainExpansionIntoAppearanceSettings() throws {
        let payload = try XCTUnwrap(
            ReactAppearanceSettingsDraftPayload(raw: validRawDraft(overrides: ["agentTaskChainExpansion": "multiple"]))
        )

        XCTAssertEqual(payload.agentTaskChainExpansion, "multiple")
        XCTAssertEqual(payload.toAppearanceSettings().agentTaskChainExpansion, "multiple")
    }

    func testDraftRejectsUnknownChainExpansion() {
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: validRawDraft(overrides: ["agentTaskChainExpansion": "all"])))
    }

    func testChainExpansionDefaultsToSingleAndDecodesAndEncodesAsSnakeCase() throws {
        XCTAssertEqual(AppearanceSettings().agentTaskChainExpansion, "single")

        let decodedWithoutField = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"preferred_font":"Helvetica-Light"}"#.utf8))
        XCTAssertEqual(decodedWithoutField.agentTaskChainExpansion, "single")

        let decodedUnknown = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"preferred_font":"Helvetica-Light","agent_task_chain_expansion":"all"}"#.utf8))
        XCTAssertEqual(decodedUnknown.agentTaskChainExpansion, "single")

        let decodedMultiple = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"preferred_font":"Helvetica-Light","agent_task_chain_expansion":"multiple"}"#.utf8))
        XCTAssertEqual(decodedMultiple.agentTaskChainExpansion, "multiple")

        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(decodedMultiple)) as? [String: Any]
        XCTAssertEqual(encoded?["agent_task_chain_expansion"] as? String, "multiple")
    }

    @MainActor
    func testAestheticSystemFollowsLoadedChainExpansionSetting() {
        AestheticSystem.loadFromSettings(AppearanceSettings(agentTaskChainExpansion: "multiple"))
        XCTAssertEqual(AestheticSystem.agentTaskChainExpansion, "multiple")

        AestheticSystem.loadFromSettings(AppearanceSettings())
        XCTAssertEqual(AestheticSystem.agentTaskChainExpansion, "single")
    }
}

final class AppearanceTextScaleSettingsTests: XCTestCase {
    private func rawDraft(overrides: [String: Any] = [:]) -> [String: Any] {
        var raw: [String: Any] = [
            "backgroundColorRed": 1.0, "backgroundColorGreen": 1.0, "backgroundColorBlue": 1.0,
            "primaryColorRed": 0.0, "primaryColorGreen": 0.188, "primaryColorBlue": 0.529,
            "secondaryColorRed": 0.2, "secondaryColorGreen": 0.333, "secondaryColorBlue": 0.608,
            "textColorRed": 0.0, "textColorGreen": 0.0, "textColorBlue": 0.0,
            "processingColorRed": 0.486, "processingColorGreen": 0.227, "processingColorBlue": 0.929,
            "processingAccentColorRed": 0.867, "processingAccentColorGreen": 0.839, "processingAccentColorBlue": 0.996,
            "preferredFont": "Helvetica-Light",
        ]
        for (key, value) in overrides { raw[key] = value }
        return raw
    }

    func testADraftWithoutTextScaleMeansOneHundredPercent() throws {
        let payload = try XCTUnwrap(ReactAppearanceSettingsDraftPayload(raw: rawDraft()))
        XCTAssertEqual(payload.textScale, 1.0)
        XCTAssertEqual(payload.toAppearanceSettings().textScale, 1.0)
    }

    func testADraftTextScaleIsSnappedAndCarriedIntoTheSettings() throws {
        let payload = try XCTUnwrap(ReactAppearanceSettingsDraftPayload(raw: rawDraft(overrides: ["textScale": 1.3])))
        XCTAssertEqual(payload.textScale, 1.25)
        XCTAssertEqual(payload.toAppearanceSettings().textScale, 1.25)
    }

    func testADraftWithANonNumericTextScaleIsRejected() {
        XCTAssertNil(ReactAppearanceSettingsDraftPayload(raw: rawDraft(overrides: ["textScale": "large"])))
    }

    func testDecodingAPayloadThatPredatesTextScaleFallsBackToOneHundredPercent() throws {
        let settings = try JSONDecoder().decode(AppearanceSettings.self, from: Data("{}".utf8))
        XCTAssertEqual(settings.textScale, 1.0)
    }

    func testDecodingSnapsAStoredOffStepValue() throws {
        let settings = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"text_scale": 1.3}"#.utf8))
        XCTAssertEqual(settings.textScale, 1.25)
    }

    func testDecodingAnUnreadableValueFallsBackToOneHundredPercentInsteadOfFailingTheWholeDecode() throws {
        let settings = try JSONDecoder().decode(AppearanceSettings.self, from: Data(#"{"text_scale": "huge", "surface_finish": "flat"}"#.utf8))
        XCTAssertEqual(settings.textScale, 1.0)
        XCTAssertEqual(settings.surfaceFinish, "flat")
    }

    func testEncodingUsesTheBackendKey() throws {
        let data = try JSONEncoder().encode(AppearanceSettings(textScale: 1.4))
        let json = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["text_scale"] as? Double, 1.4)
    }

    func testTheInitializerSnapsTheValue() {
        XCTAssertEqual(AppearanceSettings(textScale: 0.1).textScale, 0.9)
        XCTAssertEqual(AppearanceSettings(textScale: .nan).textScale, 1.0)
    }

    @MainActor
    func testLoadingSettingsMakesTheScaleAvailableToEveryThemePayload() {
        AestheticSystem.loadFromSettings(AppearanceSettings(textScale: 1.1))
        defer { AestheticSystem.loadFromSettings(AppearanceSettings()) }

        XCTAssertEqual(AestheticSystem.textScale, 1.1)
        XCTAssertEqual(AestheticWebPayload.themePayload()["textScale"] as? Double, 1.1)
        XCTAssertEqual(TranscriptionThemeSnapshot.currentJSON()["textScale"] as? Double, 1.1)
        XCTAssertEqual(AssistantSessionThemeSnapshot.currentJSON()["textScale"] as? Double, 1.1)
    }
}
