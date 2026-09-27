import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireDateTimeSettingsWebView(_ dateTimeWebView: ReactDateTimeSettingsWebView) {
        dateTimeWebView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadDateTimeSettingsAndSendInit()
            }
        }
        dateTimeWebView.onUpdateDateDisplayStyle = { [weak self] requestId, style in
            Task { @MainActor in
                await self?.putDateDisplayStyle(requestId: requestId, style: style)
            }
        }
        dateTimeWebView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[DATE_TIME_SETTINGS] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func loadDateTimeSettingsAndSendInit() async {
        dateTimeLoadGeneration += 1
        let generation = dateTimeLoadGeneration
        if let settings = await APIClient.shared.getGeneralSettings() {
            guard generation == dateTimeLoadGeneration, let dateTimeWebView else { return }
            dateTimeWebView.sendInit(dateDisplayStyle: settings.dateDisplayStyle)
        } else {
            guard generation == dateTimeLoadGeneration, let dateTimeWebView else { return }
            dateTimeWebView.sendLoadError(message: "Failed to load Date & Time settings.")
        }
    }

    private func putDateDisplayStyle(requestId: String, style: String) async {
        guard let dateTimeWebView else { return }
        dateTimeLoadGeneration += 1
        let update = GeneralSettingsUpdate(dateDisplayStyle: style)
        if let updated = await APIClient.shared.updateGeneralSettings(settingsUpdate: update) {
            APIClient.shared.cacheGeneralSettings(updated)
            dateTimeWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            dateTimeWebView.sendSnapshot(dateDisplayStyle: updated.dateDisplayStyle)
        } else {
            dateTimeWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to save the date display preference.")
        }
    }
}
