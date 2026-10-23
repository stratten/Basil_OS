import XCTest
@testable import BasilClient

final class CustomAppearanceThemeModelsTests: XCTestCase {
    private func validRawTheme(overrides: [String: Any] = [:]) -> [String: Any] {
        var raw: [String: Any] = [
            "name": "  Harbor  ",
            "backgroundColorRed": 0.1,
            "backgroundColorGreen": 0.2,
            "backgroundColorBlue": 0.3,
            "primaryColorRed": 0.4,
            "primaryColorGreen": 0.5,
            "primaryColorBlue": 0.6,
            "secondaryColorRed": 0.7,
            "secondaryColorGreen": 0.8,
            "secondaryColorBlue": 0.9,
            "textColorRed": 1.0,
            "textColorGreen": 0.95,
            "textColorBlue": 0.9,
            "surfaceFinish": "metal",
        ]
        for (key, value) in overrides {
            raw[key] = value
        }
        return raw
    }

    func testValidPayloadTrimsNameAndCarriesColorsAndFinish() throws {
        let payload = try XCTUnwrap(ReactAppearanceThemeSavePayload(raw: validRawTheme()))
        XCTAssertEqual(payload.request.name, "Harbor")
        XCTAssertEqual(payload.request.backgroundColorRed, 0.1)
        XCTAssertEqual(payload.request.textColorBlue, 0.9)
        XCTAssertEqual(payload.request.surfaceFinish, "metal")
    }

    func testRejectsBlankName() {
        XCTAssertNil(ReactAppearanceThemeSavePayload(raw: validRawTheme(overrides: ["name": "   "])))
    }

    func testRejectsNameLongerThanLimitButAcceptsExactLimit() {
        XCTAssertNil(ReactAppearanceThemeSavePayload(raw: validRawTheme(overrides: ["name": String(repeating: "x", count: 41)])))
        XCTAssertNotNil(ReactAppearanceThemeSavePayload(raw: validRawTheme(overrides: ["name": String(repeating: "x", count: 40)])))
    }

    func testRejectsOutOfRangeOrMissingColor() {
        XCTAssertNil(ReactAppearanceThemeSavePayload(raw: validRawTheme(overrides: ["primaryColorGreen": 1.5])))
        var missing = validRawTheme()
        missing.removeValue(forKey: "secondaryColorBlue")
        XCTAssertNil(ReactAppearanceThemeSavePayload(raw: missing))
    }

    func testAcceptsMetalBackdropFinish() throws {
        let payload = try XCTUnwrap(ReactAppearanceThemeSavePayload(raw: validRawTheme(overrides: ["surfaceFinish": "metal_backdrop"])))
        XCTAssertEqual(payload.request.surfaceFinish, "metal_backdrop")
    }

    func testRejectsMissingOrUnknownFinish() {
        XCTAssertNil(ReactAppearanceThemeSavePayload(raw: validRawTheme(overrides: ["surfaceFinish": "chrome"])))
        var missing = validRawTheme()
        missing.removeValue(forKey: "surfaceFinish")
        XCTAssertNil(ReactAppearanceThemeSavePayload(raw: missing))
    }

    func testThemeIDValidation() {
        XCTAssertTrue(CustomAppearanceThemeLimits.isValidThemeID("custom-" + String(repeating: "a", count: 32)))
        XCTAssertFalse(CustomAppearanceThemeLimits.isValidThemeID("duke-blue"))
        XCTAssertFalse(CustomAppearanceThemeLimits.isValidThemeID("custom-../../settings"))
        XCTAssertFalse(CustomAppearanceThemeLimits.isValidThemeID("custom-" + String(repeating: "A", count: 32)))
    }

    func testCreateRequestEncodesSnakeCaseKeys() throws {
        let payload = try XCTUnwrap(ReactAppearanceThemeSavePayload(raw: validRawTheme()))
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let object = try XCTUnwrap(try JSONSerialization.jsonObject(with: encoder.encode(payload.request)) as? [String: Any])
        XCTAssertEqual(object["name"] as? String, "Harbor")
        XCTAssertEqual(object["background_color_red"] as? Double, 0.1)
        XCTAssertEqual(object["surface_finish"] as? String, "metal")
    }

    func testResponseDecodesSnakeCaseThemes() throws {
        let json = """
        {"themes": [{"id": "custom-0123456789abcdef0123456789abcdef", "name": "Harbor", "background_color_red": 0.1, "background_color_green": 0.2, "background_color_blue": 0.3, "primary_color_red": 0.4, "primary_color_green": 0.5, "primary_color_blue": 0.6, "secondary_color_red": 0.7, "secondary_color_green": 0.8, "secondary_color_blue": 0.9, "text_color_red": 1.0, "text_color_green": 0.95, "text_color_blue": 0.9, "surface_finish": "metal"}]}
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(CustomAppearanceThemesResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.themes.count, 1)
        XCTAssertEqual(response.themes[0].name, "Harbor")
        XCTAssertEqual(response.themes[0].primaryColorGreen, 0.5)
        XCTAssertEqual(response.themes[0].surfaceFinish, "metal")
    }

    func testOutgoingThemePayloadUsesCamelCaseKeysTheWebLayerReads() {
        let theme = CustomAppearanceTheme(
            id: "custom-0123456789abcdef0123456789abcdef",
            name: "Harbor",
            backgroundColorRed: 0.1,
            backgroundColorGreen: 0.2,
            backgroundColorBlue: 0.3,
            primaryColorRed: 0.4,
            primaryColorGreen: 0.5,
            primaryColorBlue: 0.6,
            secondaryColorRed: 0.7,
            secondaryColorGreen: 0.8,
            secondaryColorBlue: 0.9,
            textColorRed: 1.0,
            textColorGreen: 0.95,
            textColorBlue: 0.9,
            surfaceFinish: "metal"
        )
        let payload = ReactAppearanceThemesWebView.themePayload(theme)
        XCTAssertEqual(payload["id"] as? String, theme.id)
        XCTAssertEqual(payload["name"] as? String, "Harbor")
        XCTAssertEqual(payload["secondaryColorBlue"] as? Double, 0.9)
        XCTAssertEqual(payload["surfaceFinish"] as? String, "metal")
        XCTAssertEqual(payload.count, 15)
    }
}
