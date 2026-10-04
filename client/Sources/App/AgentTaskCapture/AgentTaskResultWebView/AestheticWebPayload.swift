import AppKit
import SwiftUI

/// Single source of truth for the theme/font payload injected into Basil's
/// WebKit UIs (the Agent Task Result widget and the Skill Reconciliation
/// Workspace). Derived from `AestheticSystem` so centralized aesthetic changes
/// propagate to every hosted web component without manual per-view updates.
enum AestheticWebPayload {
    /// Color tokens mapped to the CSS custom properties the web components read.
    static func themePayload() -> [String: Any] {
        let backgroundPrimary = AestheticSystem.Colors.backgroundPrimary
        let semanticAppearance = semanticAppearance(for: backgroundPrimary)
        return [
            "backgroundPrimary": colorToHex(backgroundPrimary),
            "backgroundSecondary": colorToHex(AestheticSystem.Colors.backgroundSecondary, appearance: semanticAppearance),
            "backgroundTertiary": colorToHex(AestheticSystem.Colors.backgroundTertiary, appearance: semanticAppearance),
            "primary": colorToHex(AestheticSystem.Colors.primary),
            "secondary": colorToHex(AestheticSystem.Colors.secondary),
            "textPrimary": colorToHex(AestheticSystem.Colors.textPrimary),
            // `textSecondary` is a legitimately translucent color
            // (`Color.secondary` resolves to black at reduced alpha, not a
            // solid mid-gray). `colorToHex` only reads the RGB components and
            // silently discards alpha, which collapsed this specific token to
            // opaque black for every WebView-hosted consumer (rich-text
            // toolbar icons, "Conversation Only" label, etc.). `colorToCSS`
            // (already used for `separatorColor` immediately below, for the
            // identical reason) preserves alpha via `rgba(...)`, which every
            // CSS `var(--text-secondary)` consumer already accepts as a valid
            // color value with no further changes needed on the CSS side.
            "textSecondary": colorToCSS(AestheticSystem.Colors.textSecondary, appearance: semanticAppearance),
            "textTertiary": colorToHex(AestheticSystem.Colors.textTertiary, appearance: semanticAppearance),
            "separatorColor": colorToCSS(AestheticSystem.Colors.separatorColor, appearance: semanticAppearance),
            "fieldBorder": colorToHex(AestheticSystem.Colors.fieldBorder),
            "recordingBase": colorToHex(AestheticSystem.Colors.recordingBase),
            "recordingAccent": colorToHex(AestheticSystem.Colors.recordingAccent),
            "processingBase": colorToHex(AestheticSystem.Colors.processingBase),
            "processingAccent": colorToHex(AestheticSystem.Colors.processingAccent),
            "successBase": colorToHex(AestheticSystem.Colors.successBase),
            "warningBase": colorToHex(AestheticSystem.Colors.warningBase),
            "errorBase": colorToHex(AestheticSystem.Colors.errorBase),
            "readyBase": colorToHex(AestheticSystem.Colors.readyBase),
            "readyAccent": colorToHex(AestheticSystem.Colors.readyAccent),
            "surfaceFinish": AestheticSystem.surfaceFinish,
        ]
    }

    /// Font family names (base/medium/bold) derived from the preferred font.
    static func fontPayload() -> [String: Any] {
        let baseFontName = AestheticSystem.Typography.preferredFontName
        let mediumFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica"
            : baseFontName.replacingOccurrences(of: "-Light", with: "")
        let boldFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica-Bold"
            : baseFontName.replacingOccurrences(of: "-Light", with: "-Bold")

        return [
            "fontFamily": baseFontName,
            "fontFamilyMedium": mediumFontName,
            "fontFamilyBold": boldFontName,
        ]
    }

    /// Applies the persisted palette at WebKit document start, before the asynchronous React bridge is ready.
    static func documentStartThemeBootstrapScript() -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: themePayload()),
              let themeJSON = String(data: data, encoding: .utf8) else {
            return ""
        }

        return """
        (function(theme) {
            const root = document.documentElement;
            if (!root) return;
            const tokenMap = {
                backgroundPrimary: '--background-primary',
                backgroundSecondary: '--background-secondary',
                backgroundTertiary: '--background-tertiary',
                primary: '--primary',
                secondary: '--secondary',
                textSecondary: '--text-secondary',
                textTertiary: '--text-tertiary',
                recordingBase: '--recording-base',
                recordingAccent: '--recording-accent',
                processingBase: '--processing-base',
                processingAccent: '--processing-accent',
                successBase: '--success-base',
                warningBase: '--warning-base',
                errorBase: '--error-base',
                readyBase: '--ready-base',
                readyAccent: '--ready-accent'
            };
            Object.entries(tokenMap).forEach(([themeKey, cssToken]) => {
                if (theme[themeKey]) root.style.setProperty(cssToken, theme[themeKey]);
            });
            root.dataset.surfaceFinish = theme.surfaceFinish === 'metal' || theme.surfaceFinish === 'metal_backdrop' ? 'metal' : 'flat';
        })(\(themeJSON));
        """
    }

    static func colorToHex(_ color: NSColor) -> String {
        guard let rgbColor = color.usingColorSpace(.sRGB) else {
            return "#000000"
        }
        let r = Int(rgbColor.redComponent * 255)
        let g = Int(rgbColor.greenComponent * 255)
        let b = Int(rgbColor.blueComponent * 255)
        return String(format: "#%02X%02X%02X", r, g, b)
    }

    static func colorToHex(_ color: SwiftUI.Color, appearance: NSAppearance? = nil) -> String {
        let appKitColor = NSColor(color)
        if let appearance {
            var resolvedHex = "#000000"
            appearance.performAsCurrentDrawingAppearance {
                resolvedHex = colorToHex(NSColor(color))
            }
            return resolvedHex
        }
        return colorToHex(appKitColor)
    }

    static func colorToCSS(_ color: SwiftUI.Color, appearance: NSAppearance? = nil) -> String {
        let appKitColor = NSColor(color)
        if let appearance {
            var resolvedCSS = "rgba(0, 0, 0, 1)"
            appearance.performAsCurrentDrawingAppearance {
                resolvedCSS = colorToCSS(NSColor(color))
            }
            return resolvedCSS
        }
        return colorToCSS(appKitColor)
    }

    static func colorToCSS(_ color: NSColor) -> String {
        guard let rgbColor = color.usingColorSpace(.sRGB) else {
            return "rgba(0, 0, 0, 1)"
        }
        let red = Int(rgbColor.redComponent * 255)
        let green = Int(rgbColor.greenComponent * 255)
        let blue = Int(rgbColor.blueComponent * 255)
        return String(format: "rgba(%d, %d, %d, %.3f)", red, green, blue, rgbColor.alphaComponent)
    }

    static func semanticAppearance(for background: SwiftUI.Color) -> NSAppearance {
        let appKitColor = NSColor(background)
        guard let rgbColor = appKitColor.usingColorSpace(.sRGB) else {
            return NSAppearance(named: .aqua)!
        }
        let luminance = (0.2126 * rgbColor.redComponent) + (0.7152 * rgbColor.greenComponent) + (0.0722 * rgbColor.blueComponent)
        return NSAppearance(named: luminance < 0.5 ? .darkAqua : .aqua)!
    }
}
