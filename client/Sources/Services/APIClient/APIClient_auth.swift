import Foundation

// MARK: - Auth Settings API Client Extension

/// Response structure for auth settings GET requests
struct AuthSettingsGetResponse: Codable {
    let status: String
    let settings: AuthSettingsResponse
}

/// Response structure for auth settings PUT requests
struct AuthSettingsUpdateResponseWrapper: Codable {
    let status: String
    let updatedSettings: AuthSettingsResponse
    let message: String
    
    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
        case message
    }
}

extension APIClient {
    
    /// Fetches the current auth settings from the backend.
    /// - Returns: An `AuthSettingsResponse` object.
    /// - Throws: Error if the request fails.
    func getAuthSettings() async throws -> AuthSettingsResponse {
        guard let url = URL(string: "\(String(baseURL))/settings/auth") else {
            throw NSError(domain: "APIClient", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL for getAuthSettings"])
        }
        
        let (data, response) = try await URLSession.shared.data(from: url)
        
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw NSError(domain: "APIClient", code: statusCode, userInfo: [NSLocalizedDescriptionKey: "Get Auth Settings failed with status \(statusCode)"])
        }
        
        let decodedResponse = try JSONDecoder().decode(AuthSettingsGetResponse.self, from: data)
        return decodedResponse.settings
    }
    
    /// Updates the auth settings on the backend.
    /// - Parameter settings: An `AuthSettingsUpdate` object containing the settings to update.
    /// - Throws: Error if the request fails.
    func updateAuthSettings(_ settings: AuthSettingsUpdate) async throws {
        guard let url = URL(string: "\(String(baseURL))/settings/auth") else {
            throw NSError(domain: "APIClient", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL for updateAuthSettings"])
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(settings)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            // Try to get error message from response
            if let errorData = try? JSONDecoder().decode([String: String].self, from: data),
               let errorMessage = errorData["detail"] {
                throw NSError(domain: "APIClient", code: statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
            }
            throw NSError(domain: "APIClient", code: statusCode, userInfo: [NSLocalizedDescriptionKey: "Update Auth Settings failed with status \(statusCode)"])
        }
        
        #if DEBUG
        DevLogger.shared.info("✅ Auth settings updated successfully", context: "APIClient")
        #endif
    }
    
    /// Sends the access token to the Python backend for auth proxy routing.
    /// - Parameter token: The JWT access token from the auth service.
    /// - Throws: Error if the request fails.
    func setAuthToken(_ token: String) async throws {
        guard let url = URL(string: "\(String(baseURL))/settings/auth/token") else {
            throw NSError(domain: "APIClient", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL for setAuthToken"])
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let body = ["access_token": token]
        request.httpBody = try JSONEncoder().encode(body)
        
        let (_, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw NSError(domain: "APIClient", code: statusCode, userInfo: [NSLocalizedDescriptionKey: "Set Auth Token failed with status \(statusCode)"])
        }
        
        #if DEBUG
        DevLogger.shared.info("✅ Auth token sent to Python backend", context: "APIClient")
        #endif
    }
    
    /// Clears the access token from the Python backend (called on logout).
    /// - Throws: Error if the request fails.
    func clearAuthToken() async throws {
        guard let url = URL(string: "\(String(baseURL))/settings/auth/token") else {
            throw NSError(domain: "APIClient", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL for clearAuthToken"])
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        
        let (_, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw NSError(domain: "APIClient", code: statusCode, userInfo: [NSLocalizedDescriptionKey: "Clear Auth Token failed with status \(statusCode)"])
        }
        
        #if DEBUG
        DevLogger.shared.info("✅ Auth token cleared from Python backend", context: "APIClient")
        #endif
    }
    
    /// Sends the trial key to the Python backend for unauthenticated API routing.
    /// Trial keys allow $1 of API usage without requiring account creation.
    /// - Parameter trialKey: The trial key generated by TrialKeyManager.
    /// - Throws: Error if the request fails.
    func setTrialKey(_ trialKey: String) async throws {
        guard let url = URL(string: "\(String(baseURL))/settings/auth/trial-key") else {
            throw NSError(domain: "APIClient", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL for setTrialKey"])
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let body = ["trial_key": trialKey]
        request.httpBody = try JSONEncoder().encode(body)
        
        let (_, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw NSError(domain: "APIClient", code: statusCode, userInfo: [NSLocalizedDescriptionKey: "Set Trial Key failed with status \(statusCode)"])
        }
        
        #if DEBUG
        DevLogger.shared.info("🎫 Trial key sent to Python backend", context: "APIClient")
        #endif
    }
}

