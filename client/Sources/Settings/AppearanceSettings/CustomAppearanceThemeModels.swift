import Foundation

struct CustomAppearanceTheme: Codable, Equatable {
    let id: String
    let name: String
    let backgroundColorRed: Double
    let backgroundColorGreen: Double
    let backgroundColorBlue: Double
    let primaryColorRed: Double
    let primaryColorGreen: Double
    let primaryColorBlue: Double
    let secondaryColorRed: Double
    let secondaryColorGreen: Double
    let secondaryColorBlue: Double
    let textColorRed: Double
    let textColorGreen: Double
    let textColorBlue: Double
    let surfaceFinish: String
}

struct CustomAppearanceThemesResponse: Codable {
    let themes: [CustomAppearanceTheme]
}

struct CustomAppearanceThemeCreateRequest: Encodable, Equatable {
    let name: String
    let backgroundColorRed: Double
    let backgroundColorGreen: Double
    let backgroundColorBlue: Double
    let primaryColorRed: Double
    let primaryColorGreen: Double
    let primaryColorBlue: Double
    let secondaryColorRed: Double
    let secondaryColorGreen: Double
    let secondaryColorBlue: Double
    let textColorRed: Double
    let textColorGreen: Double
    let textColorBlue: Double
    let surfaceFinish: String
}

enum CustomAppearanceThemeLimits {
    static let maximumThemeCount = 24
    // Counted in Unicode scalars so the limit matches Python's len() on the backend.
    static let maximumNameLength = 40

    static func isValidThemeID(_ id: String) -> Bool {
        id.range(of: "^custom-[0-9a-f]{32}$", options: .regularExpression) != nil
    }
}

struct ReactAppearanceThemeSavePayload {
    let request: CustomAppearanceThemeCreateRequest

    /// Returns nil when the name is blank or longer than the limit after trimming, any color component is missing or outside 0...1, or the finish is not "flat" or "metal".
    init?(raw: [String: Any]) {
        func component(_ key: String) -> Double? {
            guard let value = (raw[key] as? NSNumber)?.doubleValue, value.isFinite else { return nil }
            guard value >= 0, value <= 1 else { return nil }
            return value
        }
        let name = (raw["name"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard
            !name.isEmpty,
            name.unicodeScalars.count <= CustomAppearanceThemeLimits.maximumNameLength,
            let backgroundColorRed = component("backgroundColorRed"),
            let backgroundColorGreen = component("backgroundColorGreen"),
            let backgroundColorBlue = component("backgroundColorBlue"),
            let primaryColorRed = component("primaryColorRed"),
            let primaryColorGreen = component("primaryColorGreen"),
            let primaryColorBlue = component("primaryColorBlue"),
            let secondaryColorRed = component("secondaryColorRed"),
            let secondaryColorGreen = component("secondaryColorGreen"),
            let secondaryColorBlue = component("secondaryColorBlue"),
            let textColorRed = component("textColorRed"),
            let textColorGreen = component("textColorGreen"),
            let textColorBlue = component("textColorBlue"),
            let surfaceFinish = raw["surfaceFinish"] as? String,
            ["flat", "metal"].contains(surfaceFinish)
        else { return nil }
        request = CustomAppearanceThemeCreateRequest(
            name: name,
            backgroundColorRed: backgroundColorRed,
            backgroundColorGreen: backgroundColorGreen,
            backgroundColorBlue: backgroundColorBlue,
            primaryColorRed: primaryColorRed,
            primaryColorGreen: primaryColorGreen,
            primaryColorBlue: primaryColorBlue,
            secondaryColorRed: secondaryColorRed,
            secondaryColorGreen: secondaryColorGreen,
            secondaryColorBlue: secondaryColorBlue,
            textColorRed: textColorRed,
            textColorGreen: textColorGreen,
            textColorBlue: textColorBlue,
            surfaceFinish: surfaceFinish
        )
    }
}
