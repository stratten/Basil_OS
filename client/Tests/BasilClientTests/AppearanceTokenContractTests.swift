import XCTest
@testable import BasilClient

final class AppearanceTokenContractTests: XCTestCase {
    func testContractExposesEveryDerivedAndFixedTokenName() {
        XCTAssertEqual(
            AppearanceTokenContract.derivedSurfaceTokens,
            ["surfaceRaised", "surfaceSunken", "surfaceOverlay", "surfaceSelected", "surfaceHover", "surfaceDisabled"]
        )
        XCTAssertEqual(
            AppearanceTokenContract.derivedTextTokens,
            ["textSecondary", "textTertiary", "textOnPrimary", "textOnSuccess", "textOnWarning", "textOnError"]
        )
        XCTAssertEqual(
            AppearanceTokenContract.derivedStructuralTokens,
            ["separator", "fieldBorder", "focusRing", "shadow"]
        )
        XCTAssertEqual(
            AppearanceTokenContract.fixedSemanticStateTokens,
            ["recordingBase", "recordingAccent", "successBase", "warningBase", "errorBase", "processingBase", "processingAccent", "readyBase", "readyAccent"]
        )
    }

    func testContrastRatioUsesWcagRelativeLuminance() {
        let black: AppearanceTokenContract.RGBColor = (0, 0, 0)
        let white: AppearanceTokenContract.RGBColor = (1, 1, 1)
        let gray: AppearanceTokenContract.RGBColor = (0.5, 0.5, 0.5)

        XCTAssertEqual(AppearanceTokenContract.contrastRatio(foreground: black, background: white) ?? 0, 21.0, accuracy: 0.001)
        XCTAssertEqual(AppearanceTokenContract.contrastRatio(foreground: gray, background: gray) ?? 0, 1.0, accuracy: 0.001)
    }

    func testMinimumContrastDistinguishesNormalAndLargeText() {
        let foreground: AppearanceTokenContract.RGBColor = (0.50, 0.50, 0.50)
        let background: AppearanceTokenContract.RGBColor = (1, 1, 1)

        XCTAssertEqual(AppearanceTokenContract.meetsMinimumContrast(foreground: foreground, background: background, isLargeText: false), false)
        XCTAssertEqual(AppearanceTokenContract.meetsMinimumContrast(foreground: foreground, background: background, isLargeText: true), true)
    }

    func testInvalidRgbComponentsReturnNil() {
        let invalidNegative: AppearanceTokenContract.RGBColor = (-0.1, 0, 0)
        let invalidAboveOne: AppearanceTokenContract.RGBColor = (1.1, 0, 0)
        let invalidNaN: AppearanceTokenContract.RGBColor = (Double.nan, 0, 0)
        let white: AppearanceTokenContract.RGBColor = (1, 1, 1)

        XCTAssertNil(AppearanceTokenContract.contrastRatio(foreground: invalidNegative, background: white))
        XCTAssertNil(AppearanceTokenContract.contrastRatio(foreground: invalidAboveOne, background: white))
        XCTAssertNil(AppearanceTokenContract.contrastRatio(foreground: invalidNaN, background: white))
    }
}
