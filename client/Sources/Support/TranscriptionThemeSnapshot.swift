import AppKit
import SwiftUI

/// Serializes AestheticSystem's current color/font tokens into the
/// TranscriptionThemePayload bridge shape. Trimmed subset of
/// AssistantSessionThemeSnapshot's field list — only what
/// TranscriptionWidget's React port actually renders.
enum TranscriptionThemeSnapshot {
    static func currentJSON() -> [String: Any] {
        let backgroundPrimary = AestheticSystem.Colors.backgroundPrimary
        let semanticAppearance = AestheticWebPayload.semanticAppearance(for: backgroundPrimary)
        return [
            "primary": AestheticWebPayload.colorToHex(AestheticSystem.Colors.primary),
            "secondary": AestheticWebPayload.colorToHex(AestheticSystem.Colors.secondary),
            "backgroundPrimary": AestheticWebPayload.colorToHex(backgroundPrimary),
            "textPrimary": AestheticWebPayload.colorToHex(AestheticSystem.Colors.textPrimary),
            "textSecondary": AestheticWebPayload.colorToHex(AestheticSystem.Colors.textSecondary, appearance: semanticAppearance),
            "recordingBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.recordingBase),
            "errorBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.errorBase),
            "warningBase": AestheticWebPayload.colorToHex(AestheticSystem.Colors.warningBase),
            "preferredFontName": AestheticSystem.Typography.preferredFontName,
            "surfaceFinish": AestheticSystem.surfaceFinish,
        ]
    }
}
