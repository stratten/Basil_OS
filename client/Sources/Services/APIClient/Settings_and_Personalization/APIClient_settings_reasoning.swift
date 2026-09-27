import Foundation

// MARK: - Reasoning Settings Helpers
extension APIClient {
    private static let defaultCloudReasoningModel = "claude-sonnet-4-5-20250929"
    
    /// Internal struct for decoding model settings response
    private struct ModelSettingsResponse: Codable {
        let status: String
        let settings: ModelSettingsPayload
    }
    
    private struct ModelSettingsPayload: Codable {
        var persistenceDuration: Int
        var visionModel: String
        var languageModel: String
        var reasoningModel: String
        var transcriptionModel: String
        var useApiModels: Bool
        var closeAssistantSessionOnInsert: Bool
        var autoPasteAssistantOutput: Bool
    }
    
    /// Fetches the current reasoning model from `/settings/models`.
    /// - Returns: The current reasoning model ID string
    @MainActor
    func getCurrentReasoningModel() async throws -> String {
        do {
            let raw = try await get("/settings/models")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try decoder.decode(ModelSettingsResponse.self, from: raw)
            return response.settings.reasoningModel
        } catch {
            logger.error("❌ Failed fetching current reasoning model: \(error.localizedDescription)")
            throw error
        }
    }
    
    /// Fetches the current transcription model from `/settings/models`.
    /// - Returns: The current transcription model ID string
    @MainActor
    func getCurrentTranscriptionModel() async throws -> String {
        do {
            let raw = try await get("/settings/models")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try decoder.decode(ModelSettingsResponse.self, from: raw)
            return response.settings.transcriptionModel
        } catch {
            logger.error("❌ Failed fetching current transcription model: \(error.localizedDescription)")
            throw error
        }
    }
    
    /// Updates the selected reasoning model in `/settings/models` while preserving other fields.
    @MainActor
    func updateSelectedReasoningModel(_ modelId: String) async throws {
        do {
            // Fetch current settings
            let raw = try await get("/settings/models")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            var current = try decoder.decode(ModelSettingsResponse.self, from: raw).settings

            // Update reasoning model
            current.reasoningModel = modelId

            // Persist
            let enc = JSONEncoder()
            enc.keyEncodingStrategy = .convertToSnakeCase
            let data = try enc.encode(current)
            _ = try await put("/settings/models", data: data)
        } catch {
            logger.error("❌ Failed updating reasoning model: \(error.localizedDescription)")
            throw error
        }
    }
    
    /// Enables cloud reasoning and selects the default cloud model while preserving
    /// the rest of the model settings payload returned by the backend.
    @MainActor
    func applyDefaultCloudReasoningSettings() async throws {
        do {
            let raw = try await get("/settings/models")
            guard let response = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
                  var settings = response["settings"] as? [String: Any] else {
                throw NSError(domain: "APIClient", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid model settings response"])
            }
            
            settings["use_api_models"] = true
            settings["reasoning_model"] = Self.defaultCloudReasoningModel
            settings["language_model"] = Self.defaultCloudReasoningModel
            settings["anthropic_enabled"] = true
            
            if var anthropicModels = settings["anthropic_models"] as? [String: Any] {
                anthropicModels[Self.defaultCloudReasoningModel] = true
                settings["anthropic_models"] = anthropicModels
            } else {
                settings["anthropic_models"] = [Self.defaultCloudReasoningModel: true]
            }
            
            let data = try JSONSerialization.data(withJSONObject: settings)
            _ = try await put("/settings/models", data: data)
        } catch {
            logger.error("❌ Failed applying cloud reasoning defaults: \(error.localizedDescription)")
            throw error
        }
    }
}


