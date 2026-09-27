import Foundation

extension SettingsShellWindowController {
    func wireMacContactsSettingsWebView(_ macContactsSettingsWebView: ReactMacContactsSettingsWebView) {
        macContactsSettingsWebView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadMacContactsSettingsAndSendInit()
            }
        }
        macContactsSettingsWebView.onUpdateEnabled = { [weak self] request in
            Task { @MainActor in
                await self?.updateMacContactsEnabled(request)
            }
        }
        macContactsSettingsWebView.onMalformedIntent = { type in
            #if DEBUG
            DevLogger.shared.error("[MAC_CONTACTS_SETTINGS] Malformed intent: \(type)", context: "SettingsShellWindowController")
            #endif
        }
    }

    private func loadMacContactsSettingsAndSendInit() async {
        guard let macContactsSettingsWebView else { return }
        do {
            macContactsSettingsWebView.sendInit(status: try await fetchMacContactsStatus())
        } catch {
            macContactsSettingsWebView.sendLoadError(message: "Failed to load Contacts access.")
        }
    }

    private func updateMacContactsEnabled(_ request: ReactMacContactsSettingsUpdateRequest) async {
        guard let macContactsSettingsWebView else { return }
        do {
            if request.enabled {
                let accessStatus = try await requestMacContactsAccess()
                guard accessStatus.available,
                      ["authorized", "limited"].contains(accessStatus.authorizationStatus) else {
                    macContactsSettingsWebView.sendSnapshot(status: accessStatus)
                    macContactsSettingsWebView.sendIntentResult(
                        requestId: request.requestId,
                        status: "error",
                        message: "Contacts access was not granted."
                    )
                    return
                }
            }

            let updatedBehavior = try await putMacContactsPreference(enabled: request.enabled)
            APIClient.shared.cacheBehaviorSettings(updatedBehavior)
            macContactsSettingsWebView.sendSnapshot(status: try await fetchMacContactsStatus())
            macContactsSettingsWebView.sendIntentResult(requestId: request.requestId, status: "success", message: nil)
        } catch {
            macContactsSettingsWebView.sendIntentResult(
                requestId: request.requestId,
                status: "error",
                message: "Failed to update Contacts access."
            )
        }
    }

    private func fetchMacContactsStatus() async throws -> MacContactsStatusResponse {
        let data = try await APIClient.shared.get("/personalization/contacts/mac/status")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MacContactsStatusResponse.self, from: data)
    }

    private func requestMacContactsAccess() async throws -> MacContactsStatusResponse {
        let data = try await APIClient.shared.postForData("/personalization/contacts/mac/request-access")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MacContactsStatusResponse.self, from: data)
    }

    private func putMacContactsPreference(enabled: Bool) async throws -> BehaviorSettings {
        let data = try JSONSerialization.data(withJSONObject: ["allow_mac_contacts_for_generation": enabled])
        let responseData = try await APIClient.shared.put("/settings/behavior", data: data)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        struct BehaviorSettingsUpdateResponse: Codable {
            let status: String
            let updatedSettings: BehaviorSettings
        }
        return try decoder.decode(BehaviorSettingsUpdateResponse.self, from: responseData).updatedSettings
    }
}
