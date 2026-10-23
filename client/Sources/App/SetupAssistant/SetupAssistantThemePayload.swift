enum SetupAssistantThemePayload {
    static func theme() -> [String: Any] {
        AestheticWebPayload.themePayload()
    }

    static func fonts() -> [String: Any] {
        AestheticWebPayload.fontPayload()
    }
}
