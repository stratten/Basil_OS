import Foundation

enum AppearanceTokenContract {
    typealias RGBColor = (red: Double, green: Double, blue: Double)

    static let derivedSurfaceTokens = ["surfaceRaised", "surfaceSunken", "surfaceOverlay", "surfaceSelected", "surfaceHover", "surfaceDisabled"]
    static let derivedTextTokens = ["textSecondary", "textTertiary", "textOnPrimary", "textOnSuccess", "textOnWarning", "textOnError"]
    static let derivedStructuralTokens = ["separator", "fieldBorder", "focusRing", "shadow"]
    static let fixedSemanticStateTokens = ["recordingBase", "recordingAccent", "successBase", "warningBase", "errorBase", "processingBase", "processingAccent", "readyBase", "readyAccent"]

    static func contrastRatio(foreground: RGBColor, background: RGBColor) -> Double? {
        guard let foregroundLuminance = relativeLuminance(of: foreground),
              let backgroundLuminance = relativeLuminance(of: background) else {
            return nil
        }
        let lighter = max(foregroundLuminance, backgroundLuminance)
        let darker = min(foregroundLuminance, backgroundLuminance)
        return (lighter + 0.05) / (darker + 0.05)
    }

    static func meetsMinimumContrast(
        foreground: RGBColor,
        background: RGBColor,
        isLargeText: Bool = false
    ) -> Bool? {
        guard let ratio = contrastRatio(foreground: foreground, background: background) else {
            return nil
        }
        return ratio >= (isLargeText ? 3.0 : 4.5)
    }

    static func relativeLuminance(of color: RGBColor) -> Double? {
        guard isValid(color) else { return nil }
        return (0.2126 * linearizeSrgb(color.red)) + (0.7152 * linearizeSrgb(color.green)) + (0.0722 * linearizeSrgb(color.blue))
    }

    private static func linearizeSrgb(_ component: Double) -> Double {
        component <= 0.04045 ? component / 12.92 : pow((component + 0.055) / 1.055, 2.4)
    }

    private static func isValid(_ color: RGBColor) -> Bool {
        color.red.isFinite && color.green.isFinite && color.blue.isFinite
            && (0.0...1.0).contains(color.red)
            && (0.0...1.0).contains(color.green)
            && (0.0...1.0).contains(color.blue)
    }
}
