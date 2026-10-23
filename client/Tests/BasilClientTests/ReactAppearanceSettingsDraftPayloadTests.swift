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
}
