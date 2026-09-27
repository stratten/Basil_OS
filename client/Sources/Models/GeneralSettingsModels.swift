import Foundation

// Corresponds to the GeneralSettings Pydantic model on the backend
struct GeneralSettings: Codable, Hashable {
    var hasCompletedOnboarding: Bool
    var dateDisplayStyle: String

    enum CodingKeys: String, CodingKey {
        case hasCompletedOnboarding = "has_completed_onboarding"
        case dateDisplayStyle = "date_display_style"
    }

    init(hasCompletedOnboarding: Bool, dateDisplayStyle: String = "relative") {
        self.hasCompletedOnboarding = hasCompletedOnboarding
        self.dateDisplayStyle = dateDisplayStyle
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        hasCompletedOnboarding = try container.decodeIfPresent(Bool.self, forKey: .hasCompletedOnboarding) ?? false
        dateDisplayStyle = try container.decodeIfPresent(String.self, forKey: .dateDisplayStyle) ?? "relative"
    }
}

// Corresponds to the GeneralSettingsUpdate Pydantic model on the backend
struct GeneralSettingsUpdate: Codable {
    var hasCompletedOnboarding: Bool? = nil
    var dateDisplayStyle: String? = nil

    enum CodingKeys: String, CodingKey {
        case hasCompletedOnboarding = "has_completed_onboarding"
        case dateDisplayStyle = "date_display_style"
    }
} 
