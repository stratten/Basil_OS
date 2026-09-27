struct HotkeySettingsResponse: Codable, Sendable {
    let status: String
    let settings: [String: HotkeyBinding]
}
