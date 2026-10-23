import Foundation

extension APIClient {
    func getBrowserAutomationSettings() async throws -> BrowserAutomationSettings {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let responseData = try await get("/settings/browser-automation")
        let response = try browserAutomationSettingsDecoder.decode(
            BrowserAutomationSettingsGetResponse.self,
            from: responseData
        )
        return response.settings
    }

    func updateBrowserAutomationSettings(
        _ updateData: UpdateBrowserAutomationSettingsRequest
    ) async throws -> BrowserAutomationSettings {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let requestData = try JSONEncoder().encode(updateData)
        let responseData = try await put("/settings/browser-automation", data: requestData)
        let response = try browserAutomationSettingsDecoder.decode(
            BrowserAutomationSettingsUpdateResponse.self,
            from: responseData
        )
        return response.updatedSettings
    }

    func deleteBrowserSensitiveDomainApproval(domain: String) async throws {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        guard let encodedDomain = domain.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else {
            throw APIError.invalidURL
        }

        _ = try await delete("/settings/browser-automation/sensitive-domains/\(encodedDomain)")
    }

    func clearBasilAutomationBrowserProfile() async throws {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        _ = try await post("/settings/browser-automation/automation-browser-profile/clear", body: Data())
    }

    private var browserAutomationSettingsDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

