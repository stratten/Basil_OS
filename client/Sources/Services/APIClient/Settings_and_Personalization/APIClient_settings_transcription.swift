import Foundation

// MARK: - Transcription API Models Response Types

struct TranscriptionAPIProviderStatus: Codable {
    let enabled: Bool
    let hasKey: Bool
    
    enum CodingKeys: String, CodingKey {
        case enabled
        case hasKey = "has_key"
    }
}

struct TranscriptionAPIModelsResponse: Codable {
    let status: String
    let models: [TranscriptionAPIModelInfo]
    let apiTranscriptionModelsEnabled: Bool
    let currentModel: String
    let providers: [String: TranscriptionAPIProviderStatus]?
    
    enum CodingKeys: String, CodingKey {
        case status, models, providers
        case apiTranscriptionModelsEnabled = "api_transcription_models_enabled"
        case currentModel = "current_model"
    }
}

struct TranscriptionAPIModelInfo: Codable, Identifiable {
    let id: String
    let name: String
    let displayName: String
    let provider: String
    let isApiModel: Bool
    let description: String?
    let apiModelName: String?

    enum CodingKeys: String, CodingKey {
        case id, name, provider, description
        case displayName = "display_name"
        case isApiModel = "is_api_model"
        case apiModelName = "api_model_name"
    }
}

struct TranscriptionAPIToggleResponse: Codable {
    let status: String
    let apiTranscriptionModelsEnabled: Bool
    let providersEnabled: [String: Bool]
    
    enum CodingKeys: String, CodingKey {
        case status
        case apiTranscriptionModelsEnabled = "api_transcription_models_enabled"
        case providersEnabled = "providers_enabled"
    }
}

struct TranscriptionAPIProviderUpdateResponse: Codable {
    let status: String
    let provider: [String: AnyCodable]
}

struct TranscriptionAPIModelUpdateResponse: Codable {
    let status: String
    let model: [String: AnyCodable]
}

// MARK: - Atomic Transcription Model Swap

/// Mirrors `SwapTranscriptionModelResponse` from
/// `POST /settings/transcription/model/swap`. Returned by the atomic
/// "unload current + persist preference + load new" backend flow.
struct SwapTranscriptionModelResponse: Codable {
    let modelId: String
    let loaded: Bool
    let serviceKind: String
    let elapsedMs: Int
    let noOp: Bool
    let activationStatus: String?

    enum CodingKeys: String, CodingKey {
        case modelId = "model_id"
        case loaded
        case serviceKind = "service_kind"
        case elapsedMs = "elapsed_ms"
        case noOp = "no_op"
        case activationStatus = "activation_status"
    }
}

// MARK: - Transcription Settings Helpers (separate from large APIClient_settings.swift)
extension APIClient {
    
    // MARK: - Transcription API Model Methods
    
    func getApiTranscriptionModels() async throws -> TranscriptionAPIModelsResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let data = try await get("/settings/api_models/transcription")
        let decoder = JSONDecoder()
        return try decoder.decode(TranscriptionAPIModelsResponse.self, from: data)
    }
    
    func toggleApiTranscriptionModels(enabled: Bool) async throws -> TranscriptionAPIToggleResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        struct ToggleRequest: Codable {
            let enabled: Bool
        }
        let request = ToggleRequest(enabled: enabled)
        let encoder = JSONEncoder()
        let requestData = try encoder.encode(request)
        let responseData = try await put("/settings/api_models/transcription/toggle", data: requestData)
        return try JSONDecoder().decode(TranscriptionAPIToggleResponse.self, from: responseData)
    }
    
    func updateTranscriptionProvider(provider: String, enabled: Bool) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        struct ProviderRequest: Codable {
            let enabled: Bool
        }
        let request = ProviderRequest(enabled: enabled)
        let requestData = try JSONEncoder().encode(request)
        return try await put("/settings/api_models/transcription/providers/\(provider)", data: requestData)
    }
    
    func updateTranscriptionApiModel(provider: String, modelId: String, enabled: Bool, setAsDefault: Bool = false) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        struct ModelRequest: Codable {
            let enabled: Bool
            let set_as_default: Bool
        }
        let request = ModelRequest(enabled: enabled, set_as_default: setAsDefault)
        let requestData = try JSONEncoder().encode(request)
        return try await put("/settings/api_models/transcription/\(provider)/\(modelId)", data: requestData)
    }
    
    // MARK: - Selected Transcription Model
    
    /// Updates the selected transcription model across both `/settings/transcription` and `/settings/models` endpoints.
    /// Preserves all unrelated fields and updates local cache for immediate consistency.
    @MainActor
    func updateSelectedTranscriptionModel(_ modelId: String) async throws {
        // 1) Update /settings/transcription.selected_model while preserving other fields
        do {
            let currentData = try await get("/settings/transcription")
            let current = try JSONDecoder().decode(TranscriptionSettingsResponse.self, from: currentData)

            let updated = current.settings.applying(selectedModel: modelId)

            let enc = JSONEncoder()
            let body = try enc.encode(updated)
            _ = try await put("/settings/transcription", data: body)

            // Update cache
            cacheTranscriptionSettings(updated)
        } catch {
            logger.error("❌ Failed updating /settings/transcription.selected_model: \(error.localizedDescription)")
            throw error
        }

        // 2) Update /settings/models.transcription_model while preserving other model fields
        struct ModelSettingsPayload: Codable {
            let persistenceDuration: Int
            let visionModel: String
            let languageModel: String
            let reasoningModel: String
            let transcriptionModel: String
        }

        // Backend wraps response: { "status": "success", "settings": { ... } }
        struct ModelSettingsResponse: Codable {
            let status: String
            let settings: ModelSettingsPayload
        }

        do {
            let raw = try await get("/settings/models")
            let dec = JSONDecoder()
            dec.keyDecodingStrategy = .convertFromSnakeCase
            let response = try dec.decode(ModelSettingsResponse.self, from: raw)
            var settings = response.settings
            settings = ModelSettingsPayload(
                persistenceDuration: settings.persistenceDuration,
                visionModel: settings.visionModel,
                languageModel: settings.languageModel,
                reasoningModel: settings.reasoningModel,
                transcriptionModel: modelId
            )

            let enc = JSONEncoder()
            enc.keyEncodingStrategy = .convertToSnakeCase
            let data = try enc.encode(settings)
            _ = try await put("/settings/models", data: data)
        } catch {
            logger.error("❌ Failed updating /settings/models.transcription_model: \(error.localizedDescription)")
            throw error
        }
    }

    // MARK: - Atomic Model Swap

    /// Atomically swaps the active transcription model server-side.
    ///
    /// Hits `POST /settings/transcription/model/swap`, which (a) writes
    /// the new model id to preferences, (b) unloads the currently loaded
    /// transcription model from memory, and (c) loads the new one. This
    /// is the only path that produces a *live* model swap; the existing
    /// `updateSelectedTranscriptionModel(_:)` only persists preferences
    /// and the in-memory `ModelManager` will not re-read them until the
    /// next process restart.
    ///
    /// On success the local transcription-settings cache is refreshed
    /// so any other surface reading from `cachedTranscriptionSettings`
    /// (e.g. the Settings tab) sees the new selection without a
    /// round-trip.
    @MainActor
    func swapTranscriptionModel(_ modelId: String) async throws -> SwapTranscriptionModelResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        struct SwapRequest: Codable {
            let modelId: String
            enum CodingKeys: String, CodingKey { case modelId = "model_id" }
        }

        let body = try JSONEncoder().encode(SwapRequest(modelId: modelId))
        // 180s timeout — large local Whisper variants can take 30-90s
        // to load from cold cache; we want to wait through that rather
        // than time out and leave the UI in a stuck `isSwapping` state.
        let raw = try await post("/settings/transcription/model/swap", body: body, timeout: 180)
        let response = try JSONDecoder().decode(SwapTranscriptionModelResponse.self, from: raw)

        // Refresh the cached transcription settings so other surfaces
        // (Settings tab, status readouts) reflect the new selection
        // without an extra GET.
        if let cached = cachedTranscriptionSettings {
            let updated = cached.applying(selectedModel: response.modelId)
            cacheTranscriptionSettings(updated)
        }

        return response
    }
}


