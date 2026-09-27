import SwiftUI

@MainActor
final class BrowserAutomationSettingsViewModel: ObservableObject {
    @Published var settings: BrowserAutomationSettings?
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    func loadSettings() async {
        isLoading = true
        errorMessage = nil

        do {
            settings = try await apiClient.getBrowserAutomationSettings()
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to load browser automation settings: \(error)", context: "BrowserAutomationSettingsViewModel")
            #endif
            errorMessage = "Failed to load browser automation settings: \(error.localizedDescription)"
        }

        isLoading = false
    }

    func updateSensitiveFillPolicy(_ policy: BrowserSensitiveFillPolicy) async {
        await updateSettings(UpdateBrowserAutomationSettingsRequest(sensitiveFillPolicy: policy))
    }

    func updateForegroundControlPolicy(_ policy: BrowserForegroundControlPolicy) async {
        await updateSettings(UpdateBrowserAutomationSettingsRequest(foregroundControlPolicy: policy))
    }

    func updateDefaultSessionMode(_ sessionMode: BrowserAutomationSessionMode) async {
        await updateSettings(UpdateBrowserAutomationSettingsRequest(defaultSessionMode: sessionMode))
    }

    func updatePreferredUserBrowser(_ browser: BrowserPreferredUserBrowser) async {
        await updateSettings(UpdateBrowserAutomationSettingsRequest(preferredUserBrowser: browser))
    }

    func updateShowActionHighlights(_ enabled: Bool) async {
        await updateSettings(UpdateBrowserAutomationSettingsRequest(showActionHighlights: enabled))
    }

    func updateRecordBrowserActionTrace(_ enabled: Bool) async {
        await updateSettings(UpdateBrowserAutomationSettingsRequest(recordBrowserActionTrace: enabled))
    }

    func updateAllowVisualFallback(_ enabled: Bool) async {
        await updateSettings(UpdateBrowserAutomationSettingsRequest(allowVisualFallback: enabled))
    }

    func removeRememberedDomain(_ domain: String) async {
        do {
            try await apiClient.deleteBrowserSensitiveDomainApproval(domain: domain)
            settings?.approvedSensitiveFillDomains.removeAll { $0.domain == domain }
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to remove browser sensitive-fill domain \(domain): \(error)", context: "BrowserAutomationSettingsViewModel")
            #endif
            errorMessage = "Failed to remove \(domain): \(error.localizedDescription)"
        }
    }

    func clearBasilAutomationBrowserProfile() async {
        do {
            try await apiClient.clearBasilAutomationBrowserProfile()
            errorMessage = nil
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to clear Basil Automation Browser profile: \(error)", context: "BrowserAutomationSettingsViewModel")
            #endif
            errorMessage = "Failed to clear Basil Automation Browser profile: \(error.localizedDescription)"
        }
    }

    private func updateSettings(_ request: UpdateBrowserAutomationSettingsRequest) async {
        do {
            settings = try await apiClient.updateBrowserAutomationSettings(request)
            errorMessage = nil
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to update browser automation settings: \(error)", context: "BrowserAutomationSettingsViewModel")
            #endif
            errorMessage = "Failed to update browser automation settings: \(error.localizedDescription)"
        }
    }
}

