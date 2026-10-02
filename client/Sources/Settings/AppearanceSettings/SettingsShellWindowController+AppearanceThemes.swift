import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireAppearanceThemesWebView(_ appearanceThemesWebView: ReactAppearanceThemesWebView) {
        appearanceThemesWebView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadAppearanceThemesAndSendInit()
            }
        }
        appearanceThemesWebView.onSaveTheme = { [weak self] requestId, payload in
            Task { @MainActor in
                await self?.createAppearanceTheme(requestId: requestId, payload: payload)
            }
        }
        appearanceThemesWebView.onDeleteTheme = { [weak self] requestId, themeId in
            Task { @MainActor in
                await self?.deleteAppearanceTheme(requestId: requestId, themeId: themeId)
            }
        }
        appearanceThemesWebView.onRejectedIntent = { [weak appearanceThemesWebView] requestId in
            appearanceThemesWebView?.sendIntentResult(
                requestId: requestId,
                status: "error",
                message: "The theme request could not be completed."
            )
        }
        appearanceThemesWebView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[APPEARANCE_THEMES] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func decodeAppearanceThemes(_ data: Data) throws -> [CustomAppearanceTheme] {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(CustomAppearanceThemesResponse.self, from: data).themes
    }

    private func fetchAppearanceThemes() async throws -> [CustomAppearanceTheme] {
        try decodeAppearanceThemes(try await APIClient.shared.get("/settings/appearance/themes"))
    }

    private func loadAppearanceThemesAndSendInit() async {
        appearanceThemesLoadGeneration += 1
        let generation = appearanceThemesLoadGeneration
        do {
            let themes = try await fetchAppearanceThemes()
            guard generation == appearanceThemesLoadGeneration, let appearanceThemesWebView else { return }
            appearanceThemesWebView.sendInit(themes: themes)
        } catch {
            guard generation == appearanceThemesLoadGeneration, let appearanceThemesWebView else { return }
            appearanceThemesWebView.sendLoadError(message: "Failed to load saved themes.")
        }
    }

    private func createAppearanceTheme(requestId: String, payload: ReactAppearanceThemeSavePayload) async {
        guard let appearanceThemesWebView else { return }
        appearanceThemesLoadGeneration += 1
        do {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let body = try encoder.encode(payload.request)
            let data = try await APIClient.shared.post("/settings/appearance/themes", body: body, timeout: 30)
            let themes = try decodeAppearanceThemes(data)
            appearanceThemesWebView.sendSnapshot(themes: themes)
            appearanceThemesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch APIError.serverError(statusCode: 409) {
            appearanceThemesWebView.sendIntentResult(requestId: requestId, status: "error", message: "A theme with that name already exists.")
        } catch APIError.serverError(statusCode: 400) {
            appearanceThemesWebView.sendIntentResult(
                requestId: requestId,
                status: "error",
                message: "You can save up to \(CustomAppearanceThemeLimits.maximumThemeCount) custom themes."
            )
        } catch {
            appearanceThemesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to save the theme.")
        }
    }

    private func deleteAppearanceTheme(requestId: String, themeId: String) async {
        guard let appearanceThemesWebView else { return }
        appearanceThemesLoadGeneration += 1
        do {
            _ = try await APIClient.shared.delete("/settings/appearance/themes/\(themeId)")
        } catch APIError.serverError(statusCode: 404) {
            // Already gone; fall through so the refreshed list removes the stale swatch.
        } catch {
            appearanceThemesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to delete the theme.")
            return
        }
        do {
            let themes = try await fetchAppearanceThemes()
            appearanceThemesWebView.sendSnapshot(themes: themes)
            appearanceThemesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            appearanceThemesWebView.sendIntentResult(
                requestId: requestId,
                status: "error",
                message: "The theme was deleted, but the theme list could not be refreshed."
            )
        }
    }
}
