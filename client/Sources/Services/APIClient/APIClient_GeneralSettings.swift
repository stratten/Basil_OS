import Foundation

// Standard response structure for settings GET requests
struct GeneralSettingsResponse: Codable {
    let status: String
    let settings: GeneralSettings
}

// Standard response structure for settings PUT requests
struct GeneralSettingsUpdateResponse: Codable {
    let status: String
    let updatedSettings: GeneralSettings
    let message: String

    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
        case message
    }
}

extension APIClient {
    
    /// Fetches the current general settings from the backend.
    /// - Returns: A `GeneralSettings` object or `nil` if an error occurs.
    func getGeneralSettings() async -> GeneralSettings? {
        guard let url = URL(string: "\(String(baseURL))/settings/general") else {
            logger.error("❌ Invalid URL for getGeneralSettings")
            return nil
        }
        
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
                let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
                logger.error("❌ Get General Settings: Invalid response or status code \(statusCode).")
                return nil
            }
            
            let decodedResponse = try JSONDecoder().decode(GeneralSettingsResponse.self, from: data)
            return decodedResponse.settings
        } catch let DecodingError.dataCorrupted(context) {
            logger.error("❌ Get General Settings: Data corrupted: \(String(describing: context))")
            return nil
        } catch let DecodingError.keyNotFound(key, context) {
            logger.error("❌ Get General Settings: Key '\(String(describing: key))' not found: \(String(describing: context.debugDescription)), codingPath: \(String(describing: context.codingPath))")
            return nil
        } catch let DecodingError.valueNotFound(value, context) {
            logger.error("❌ Get General Settings: Value '\(String(describing: value))' not found: \(String(describing: context.debugDescription)), codingPath: \(String(describing: context.codingPath))")
            return nil
        } catch let DecodingError.typeMismatch(type, context) {
            logger.error("❌ Get General Settings: Type '\(String(describing: type))' mismatch: \(String(describing: context.debugDescription)), codingPath: \(String(describing: context.codingPath))")
            return nil
        } catch {
            logger.error("❌ Get General Settings: An unexpected error occurred: \(error.localizedDescription)")
            return nil
        }
    }
    
    /// Updates the general settings on the backend.
    /// - Parameter settingsUpdate: A `GeneralSettingsUpdate` object containing the settings to update.
    /// - Returns: The updated `GeneralSettings` object or `nil` if an error occurs.
    func updateGeneralSettings(settingsUpdate: GeneralSettingsUpdate) async -> GeneralSettings? {
        guard let url = URL(string: "\(String(baseURL))/settings/general") else {
            logger.error("❌ Invalid URL for updateGeneralSettings")
            return nil
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        do {
            request.httpBody = try JSONEncoder().encode(settingsUpdate)
        } catch {
            logger.error("❌ Update General Settings: Failed to encode settings: \(error.localizedDescription)")
            return nil
        }
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode) else {
                let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
                logger.error("❌ Update General Settings: Invalid response or status code \(statusCode).")
                // TODO: Handle specific error messages from backend if available in data
                return nil
            }
            
            let decodedResponse = try JSONDecoder().decode(GeneralSettingsUpdateResponse.self, from: data)
            #if DEBUG
            logger.info("✅ General settings updated successfully: \(decodedResponse.message)")
            #endif
            return decodedResponse.updatedSettings
        } catch {
            logger.error("❌ Update General Settings: Failed to decode response or other error: \(error.localizedDescription)")
            return nil
        }
    }
} 