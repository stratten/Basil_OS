import Foundation

@MainActor
protocol ReactAppearanceSettingsBridgeOutput: AnyObject {
    func sendInit(revision: Int, settings: AppearanceSettings, availableFonts: [String])
    func sendSnapshot(revision: Int, settings: AppearanceSettings, availableFonts: [String])
    func sendThemeChanged()
    func sendIntentResult(requestId: String, status: String, message: String?)
    func sendColorPicked(field: ReactAppearanceColorPickerField, red: Double, green: Double, blue: Double)
}

extension ReactAppearanceSettingsWebView: ReactAppearanceSettingsBridgeOutput {
    func sendInit(revision: Int, settings: AppearanceSettings, availableFonts: [String]) {
        var event = settingsPayload(revision: revision, settings: settings, availableFonts: availableFonts)
        event["type"] = "init"
        event["protocolVersion"] = 1
        event["theme"] = AestheticWebPayload.themePayload()
        event["fonts"] = AestheticWebPayload.fontPayload()
        callJS("window.basilAppearanceSettings && window.basilAppearanceSettings.onEvent", args: event)
    }

    func sendSnapshot(revision: Int, settings: AppearanceSettings, availableFonts: [String]) {
        var event = settingsPayload(revision: revision, settings: settings, availableFonts: availableFonts)
        event["type"] = "snapshot"
        event["protocolVersion"] = 1
        callJS("window.basilAppearanceSettings && window.basilAppearanceSettings.onEvent", args: event)
    }

    func sendThemeChanged() {
        let event: [String: Any] = [
            "type": "themeChanged",
            "theme": AestheticWebPayload.themePayload(),
            "fonts": AestheticWebPayload.fontPayload(),
        ]
        callJS("window.basilAppearanceSettings && window.basilAppearanceSettings.onEvent", args: event)
    }

    func sendIntentResult(requestId: String, status: String, message: String?) {
        var event: [String: Any] = ["type": "intentResult", "requestId": requestId, "status": status]
        if let message {
            event["message"] = message
        }
        callJS("window.basilAppearanceSettings && window.basilAppearanceSettings.onEvent", args: event)
    }

    func sendColorPicked(field: ReactAppearanceColorPickerField, red: Double, green: Double, blue: Double) {
        let event: [String: Any] = [
            "type": "colorPicked",
            "fieldId": field.rawValue,
            "red": red,
            "green": green,
            "blue": blue,
        ]
        callJS("window.basilAppearanceSettings && window.basilAppearanceSettings.onEvent", args: event)
    }

    private func settingsPayload(revision: Int, settings: AppearanceSettings, availableFonts: [String]) -> [String: Any] {
        [
            "revision": revision,
            "availableFonts": availableFonts,
            "settings": [
                "backgroundColorRed": settings.backgroundColorRed,
                "backgroundColorGreen": settings.backgroundColorGreen,
                "backgroundColorBlue": settings.backgroundColorBlue,
                "primaryColorRed": settings.primaryColorRed,
                "primaryColorGreen": settings.primaryColorGreen,
                "primaryColorBlue": settings.primaryColorBlue,
                "secondaryColorRed": settings.secondaryColorRed,
                "secondaryColorGreen": settings.secondaryColorGreen,
                "secondaryColorBlue": settings.secondaryColorBlue,
                "textColorRed": settings.textColorRed,
                "textColorGreen": settings.textColorGreen,
                "textColorBlue": settings.textColorBlue,
                "processingColorRed": settings.processingColorRed,
                "processingColorGreen": settings.processingColorGreen,
                "processingColorBlue": settings.processingColorBlue,
                "processingAccentColorRed": settings.processingAccentColorRed,
                "processingAccentColorGreen": settings.processingAccentColorGreen,
                "processingAccentColorBlue": settings.processingAccentColorBlue,
                "preferredFont": settings.preferredFont,
                "surfaceFinish": settings.surfaceFinish,
            ],
        ]
    }
}
