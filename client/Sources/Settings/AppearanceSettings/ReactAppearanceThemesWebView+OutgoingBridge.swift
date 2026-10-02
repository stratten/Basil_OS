import Foundation

@MainActor
protocol ReactAppearanceThemesBridgeOutput: AnyObject {
    func sendInit(themes: [CustomAppearanceTheme])
    func sendSnapshot(themes: [CustomAppearanceTheme])
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendLoadError(message: String)
}

extension ReactAppearanceThemesWebView: ReactAppearanceThemesBridgeOutput {
    func sendInit(themes: [CustomAppearanceTheme]) {
        let event: [String: Any] = [
            "type": "init",
            "protocolVersion": 1,
            "themes": themes.map(Self.themePayload),
        ]
        callJS("window.basilAppearanceThemes && window.basilAppearanceThemes.onEvent", args: event)
    }

    func sendSnapshot(themes: [CustomAppearanceTheme]) {
        let event: [String: Any] = [
            "type": "snapshot",
            "themes": themes.map(Self.themePayload),
        ]
        callJS("window.basilAppearanceThemes && window.basilAppearanceThemes.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilAppearanceThemes && window.basilAppearanceThemes.onEvent", args: event)
    }

    func sendLoadError(message: String) {
        let event: [String: Any] = ["type": "loadError", "message": message]
        callJS("window.basilAppearanceThemes && window.basilAppearanceThemes.onEvent", args: event)
    }

    nonisolated static func themePayload(_ theme: CustomAppearanceTheme) -> [String: Any] {
        [
            "id": theme.id,
            "name": theme.name,
            "backgroundColorRed": theme.backgroundColorRed,
            "backgroundColorGreen": theme.backgroundColorGreen,
            "backgroundColorBlue": theme.backgroundColorBlue,
            "primaryColorRed": theme.primaryColorRed,
            "primaryColorGreen": theme.primaryColorGreen,
            "primaryColorBlue": theme.primaryColorBlue,
            "secondaryColorRed": theme.secondaryColorRed,
            "secondaryColorGreen": theme.secondaryColorGreen,
            "secondaryColorBlue": theme.secondaryColorBlue,
            "textColorRed": theme.textColorRed,
            "textColorGreen": theme.textColorGreen,
            "textColorBlue": theme.textColorBlue,
            "surfaceFinish": theme.surfaceFinish,
        ]
    }
}
