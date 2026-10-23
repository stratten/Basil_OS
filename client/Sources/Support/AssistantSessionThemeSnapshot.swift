import AppKit
import SwiftUI

/// Serializes AestheticSystem's current color and font tokens into the shared AssistantSessionThemePayload bridge shape.
enum AssistantSessionThemeSnapshot {
    static func currentJSON() -> [String: Any] {
        let backgroundPrimary = AestheticSystem.Colors.backgroundPrimary
        let semanticAppearance = AestheticWebPayload.semanticAppearance(for: backgroundPrimary)
        return [
            "primary": AestheticWebPayload.colorToHex(AestheticSystem.Colors.primary),
            "secondary": AestheticWebPayload.colorToHex(AestheticSystem.Colors.secondary),
            "backgroundPrimary": AestheticWebPayload.colorToHex(backgroundPrimary),
            "backgroundSecondary": cssColor(AestheticSystem.Colors.backgroundSecondary, appearance: semanticAppearance),
            "textPrimary": AestheticWebPayload.colorToHex(AestheticSystem.Colors.textPrimary),
            "textSecondary": cssColor(AestheticSystem.Colors.textSecondary, appearance: semanticAppearance),
            "textTertiary": cssColor(AestheticSystem.Colors.textTertiary, appearance: semanticAppearance),
            "recordingBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.recordingBase),
            "recordingAccent": AestheticWebPayload.colorToHex(AestheticSystem.Colors.recordingAccent),
            "readyBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.readyBase),
            "readyAccent": AestheticWebPayload.colorToHex(AestheticSystem.Colors.readyAccent),
            "processingBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.processingBase),
            "processingAccent": AestheticWebPayload.colorToHex(AestheticSystem.Colors.processingAccent),
            "successBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.successBase),
            "errorBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.errorBase),
            "preferredFontName": AestheticSystem.Typography.preferredFontName,
            "surfaceFinish": AestheticSystem.surfaceFinish,
        ]
    }

    private static func cssColor(_ color: SwiftUI.Color, appearance: NSAppearance) -> String {
        var resolvedColor: NSColor?
        appearance.performAsCurrentDrawingAppearance {
            resolvedColor = NSColor(color).usingColorSpace(.sRGB)
        }
        guard let resolvedColor else {
            return "#000000"
        }
        return String(
            format: "rgba(%d, %d, %d, %.3f)",
            Int(resolvedColor.redComponent * 255),
            Int(resolvedColor.greenComponent * 255),
            Int(resolvedColor.blueComponent * 255),
            resolvedColor.alphaComponent
        )
    }
}
