import SwiftUI

// MARK: - Models
struct AppearanceSettings: Codable {
    var backgroundColorRed: Double
    var backgroundColorGreen: Double
    var backgroundColorBlue: Double
    var primaryColorRed: Double
    var primaryColorGreen: Double
    var primaryColorBlue: Double
    var secondaryColorRed: Double
    var secondaryColorGreen: Double
    var secondaryColorBlue: Double
    var textColorRed: Double
    var textColorGreen: Double
    var textColorBlue: Double
    var surfaceFinish: String
    // Processing bubble colors. Mirror UIPreferences on the backend so the
    // AssistantSession/AgentTask/Transcription "thinking" bubbles read from the same
    // persisted values. Defaults are sourced from `AestheticSystem.Colors`
    // (currently Royal Purple #7C3AED / #DDD6FE) via the static helpers
    // below so there is exactly one Swift literal site for the processing
    // color across the whole app. Edit `AestheticSystem.swift` to change.
    var processingColorRed: Double
    var processingColorGreen: Double
    var processingColorBlue: Double
    var processingAccentColorRed: Double
    var processingAccentColorGreen: Double
    var processingAccentColorBlue: Double
    var preferredFont: String

    /// Surface finishes accepted by the backend `surface_finish` field.
    static let supportedSurfaceFinishes: Set<String> = ["flat", "metal", "metal_backdrop"]

    /// Surface finish of the shipped default theme; mirrors the backend `surface_finish` default.
    static let defaultSurfaceFinish = "metal_backdrop"

    // Materialize the canonical processing-color components once and reuse
    // them everywhere in this file (init defaults, decoder fallbacks, the
    // `@Published` initial values on the view-model, and resetToDefaults).
    // Static let so the `Color.components` round-trip through NSColor only
    // happens on first access.
    static let defaultProcessingBaseComponents: (red: Double, green: Double, blue: Double) = {
        let c = AestheticSystem.Colors.defaultProcessingBase.components
        return (c.red, c.green, c.blue)
    }()
    static let defaultProcessingAccentComponents: (red: Double, green: Double, blue: Double) = {
        let c = AestheticSystem.Colors.defaultProcessingAccent.components
        return (c.red, c.green, c.blue)
    }()
    
    enum CodingKeys: String, CodingKey {
        case backgroundColorRed = "background_color_red"
        case backgroundColorGreen = "background_color_green"
        case backgroundColorBlue = "background_color_blue"
        case primaryColorRed = "primary_color_red"
        case primaryColorGreen = "primary_color_green"
        case primaryColorBlue = "primary_color_blue"
        case secondaryColorRed = "secondary_color_red"
        case secondaryColorGreen = "secondary_color_green"
        case secondaryColorBlue = "secondary_color_blue"
        case textColorRed = "text_color_red"
        case textColorGreen = "text_color_green"
        case textColorBlue = "text_color_blue"
        case surfaceFinish = "surface_finish"
        case processingColorRed = "processing_color_red"
        case processingColorGreen = "processing_color_green"
        case processingColorBlue = "processing_color_blue"
        case processingAccentColorRed = "processing_accent_color_red"
        case processingAccentColorGreen = "processing_accent_color_green"
        case processingAccentColorBlue = "processing_accent_color_blue"
        case preferredFont = "preferred_font"
    }
    
    init(backgroundColorRed: Double = 1.0,
         backgroundColorGreen: Double = 1.0,
         backgroundColorBlue: Double = 1.0,
         primaryColorRed: Double = 0.0,
         primaryColorGreen: Double = 0.188,
         primaryColorBlue: Double = 0.529,
         secondaryColorRed: Double = 0.2,
         secondaryColorGreen: Double = 0.333,
         secondaryColorBlue: Double = 0.608,
         textColorRed: Double = 0.0,
         textColorGreen: Double = 0.0,
         textColorBlue: Double = 0.0,
         surfaceFinish: String = AppearanceSettings.defaultSurfaceFinish,
         processingColorRed: Double = AppearanceSettings.defaultProcessingBaseComponents.red,
         processingColorGreen: Double = AppearanceSettings.defaultProcessingBaseComponents.green,
         processingColorBlue: Double = AppearanceSettings.defaultProcessingBaseComponents.blue,
         processingAccentColorRed: Double = AppearanceSettings.defaultProcessingAccentComponents.red,
         processingAccentColorGreen: Double = AppearanceSettings.defaultProcessingAccentComponents.green,
         processingAccentColorBlue: Double = AppearanceSettings.defaultProcessingAccentComponents.blue,
         preferredFont: String = "Helvetica-Light") {
        self.backgroundColorRed = backgroundColorRed
        self.backgroundColorGreen = backgroundColorGreen
        self.backgroundColorBlue = backgroundColorBlue
        self.primaryColorRed = primaryColorRed
        self.primaryColorGreen = primaryColorGreen
        self.primaryColorBlue = primaryColorBlue
        self.secondaryColorRed = secondaryColorRed
        self.secondaryColorGreen = secondaryColorGreen
        self.secondaryColorBlue = secondaryColorBlue
        self.textColorRed = textColorRed
        self.textColorGreen = textColorGreen
        self.textColorBlue = textColorBlue
        self.surfaceFinish = surfaceFinish
        self.processingColorRed = processingColorRed
        self.processingColorGreen = processingColorGreen
        self.processingColorBlue = processingColorBlue
        self.processingAccentColorRed = processingAccentColorRed
        self.processingAccentColorGreen = processingAccentColorGreen
        self.processingAccentColorBlue = processingAccentColorBlue
        self.preferredFont = preferredFont
    }

    // Custom decoder so older payloads (or local caches) that predate the
    // processing color fields still decode and fall back to the
    // AestheticSystem defaults (Royal Purple) instead of throwing a "key not
    // found" error. Without this, any cached AppearanceSettings written
    // before the processing-color fields existed would fail to decode and
    // the app would lose the user's full appearance config.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        backgroundColorRed = try container.decodeIfPresent(Double.self, forKey: .backgroundColorRed) ?? 1.0
        backgroundColorGreen = try container.decodeIfPresent(Double.self, forKey: .backgroundColorGreen) ?? 1.0
        backgroundColorBlue = try container.decodeIfPresent(Double.self, forKey: .backgroundColorBlue) ?? 1.0
        primaryColorRed = try container.decodeIfPresent(Double.self, forKey: .primaryColorRed) ?? 0.0
        primaryColorGreen = try container.decodeIfPresent(Double.self, forKey: .primaryColorGreen) ?? 0.188
        primaryColorBlue = try container.decodeIfPresent(Double.self, forKey: .primaryColorBlue) ?? 0.529
        secondaryColorRed = try container.decodeIfPresent(Double.self, forKey: .secondaryColorRed) ?? 0.2
        secondaryColorGreen = try container.decodeIfPresent(Double.self, forKey: .secondaryColorGreen) ?? 0.333
        secondaryColorBlue = try container.decodeIfPresent(Double.self, forKey: .secondaryColorBlue) ?? 0.608
        textColorRed = try container.decodeIfPresent(Double.self, forKey: .textColorRed) ?? 0.0
        textColorGreen = try container.decodeIfPresent(Double.self, forKey: .textColorGreen) ?? 0.0
        textColorBlue = try container.decodeIfPresent(Double.self, forKey: .textColorBlue) ?? 0.0
        let decodedSurfaceFinish = try container.decodeIfPresent(String.self, forKey: .surfaceFinish) ?? AppearanceSettings.defaultSurfaceFinish
        surfaceFinish = AppearanceSettings.supportedSurfaceFinishes.contains(decodedSurfaceFinish) ? decodedSurfaceFinish : AppearanceSettings.defaultSurfaceFinish
        let baseDefaults = AppearanceSettings.defaultProcessingBaseComponents
        let accentDefaults = AppearanceSettings.defaultProcessingAccentComponents
        processingColorRed = try container.decodeIfPresent(Double.self, forKey: .processingColorRed) ?? baseDefaults.red
        processingColorGreen = try container.decodeIfPresent(Double.self, forKey: .processingColorGreen) ?? baseDefaults.green
        processingColorBlue = try container.decodeIfPresent(Double.self, forKey: .processingColorBlue) ?? baseDefaults.blue
        processingAccentColorRed = try container.decodeIfPresent(Double.self, forKey: .processingAccentColorRed) ?? accentDefaults.red
        processingAccentColorGreen = try container.decodeIfPresent(Double.self, forKey: .processingAccentColorGreen) ?? accentDefaults.green
        processingAccentColorBlue = try container.decodeIfPresent(Double.self, forKey: .processingAccentColorBlue) ?? accentDefaults.blue
        preferredFont = try container.decodeIfPresent(String.self, forKey: .preferredFont) ?? "Helvetica-Light"
    }
    
    // Convenience computed properties
    var backgroundColor: Color {
        Color(red: backgroundColorRed, green: backgroundColorGreen, blue: backgroundColorBlue)
    }
    
    var primaryColor: Color {
        Color(red: primaryColorRed, green: primaryColorGreen, blue: primaryColorBlue)
    }
    
    var secondaryColor: Color {
        Color(red: secondaryColorRed, green: secondaryColorGreen, blue: secondaryColorBlue)
    }
    
    var textColor: Color {
        Color(red: textColorRed, green: textColorGreen, blue: textColorBlue)
    }

    var processingColor: Color {
        Color(red: processingColorRed, green: processingColorGreen, blue: processingColorBlue)
    }

    var processingAccentColor: Color {
        Color(red: processingAccentColorRed, green: processingAccentColorGreen, blue: processingAccentColorBlue)
    }
    
    // Helper to create from Color objects. Processing base/accent are optional
    // so existing callers (which don't yet expose processing colors in their
    // UI) keep working; passing nil preserves the defaults defined above.
    static func from(backgroundColor: Color,
                     primaryColor: Color,
                     secondaryColor: Color,
                     textColor: Color,
                     processingColor: Color? = nil,
                     processingAccentColor: Color? = nil,
                     preferredFont: String) -> AppearanceSettings {
        let backgroundComponents = backgroundColor.components
        let primaryComponents = primaryColor.components
        let secondaryComponents = secondaryColor.components
        let textComponents = textColor.components
        let processingComponents = processingColor?.components
        let processingAccentComponents = processingAccentColor?.components

        var settings = AppearanceSettings(
            backgroundColorRed: backgroundComponents.red,
            backgroundColorGreen: backgroundComponents.green,
            backgroundColorBlue: backgroundComponents.blue,
            primaryColorRed: primaryComponents.red,
            primaryColorGreen: primaryComponents.green,
            primaryColorBlue: primaryComponents.blue,
            secondaryColorRed: secondaryComponents.red,
            secondaryColorGreen: secondaryComponents.green,
            secondaryColorBlue: secondaryComponents.blue,
            textColorRed: textComponents.red,
            textColorGreen: textComponents.green,
            textColorBlue: textComponents.blue,
            preferredFont: preferredFont
        )
        if let processingComponents {
            settings.processingColorRed = processingComponents.red
            settings.processingColorGreen = processingComponents.green
            settings.processingColorBlue = processingComponents.blue
        }
        if let processingAccentComponents {
            settings.processingAccentColorRed = processingAccentComponents.red
            settings.processingAccentColorGreen = processingAccentComponents.green
            settings.processingAccentColorBlue = processingAccentComponents.blue
        }
        return settings
    }
}

// API response wrapper
struct AppearanceSettingsResponse: Codable {
    let status: String
    let settings: AppearanceSettings
}
