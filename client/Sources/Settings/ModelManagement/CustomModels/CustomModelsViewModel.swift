//
//  CustomModelsViewModel.swift
//  BasilClient
//
//  View model for managing user-defined custom models.
//

import Foundation

// MARK: - Custom Models View Model

@MainActor
class CustomModelsViewModel: ObservableObject {
    @Published var customModels: [CustomModelConfig] = []
    @Published var isLoading = false
    @Published var lastError: String?
    
    private let apiClient = APIClient.shared
    
    func loadModels() async {
        isLoading = true
        lastError = nil
        
        do {
            // Fetch raw data and decode manually for reliable parsing
            let rawData = try await apiClient.get("/models/custom")
            let decoder = JSONDecoder()
            let response = try decoder.decode(CustomModelsListResponse.self, from: rawData)
            
            customModels = response.models.map { (key, value) in
                CustomModelConfig(
                    modelId: key,
                    displayName: value.displayName.isEmpty ? key : value.displayName,
                    handler: value.handler,
                    baseUrl: value.baseUrl,
                    modelIdentifier: value.modelIdentifier,
                    modelPath: value.modelPath,
                    downloadUrl: value.downloadUrl,
                    contextWindow: value.contextWindow,
                    maxOutputTokens: value.maxOutputTokens,
                    requiresAuth: value.requiresAuth,
                    apiKeyName: value.apiKeyName,
                    capabilities: value.capabilities,
                    features: value.features,
                    featureConfig: value.featureConfig,
                    toolRendering: value.toolRendering,
                    toolCallFormat: value.toolCallFormat,
                    description: value.description,
                    fileSize: value.fileSize,
                    fileSizeHuman: value.fileSizeHuman
                )
            }
            // Sort: API models first, then local; alphabetically within each category.
            .sorted { model1, model2 in
                if model1.isLocal != model2.isLocal {
                    return !model1.isLocal // API (isLocal=false) comes before local (isLocal=true)
                }
                return model1.displayName.localizedCaseInsensitiveCompare(model2.displayName) == .orderedAscending
            }
        } catch {
            lastError = error.localizedDescription
            DevLogger.shared.error("Failed to load custom models: \(error)", context: "CustomModels")
        }
        
        isLoading = false
    }
    
    func createModel(
        modelId: String,
        displayName: String,
        handler: String,
        baseUrl: String?,
        modelIdentifier: String?,
        modelPath: String?,
        downloadUrl: String?,
        contextWindow: Int,
        maxOutputTokens: Int,
        requiresAuth: Bool,
        apiKey: String?,
        capabilities: [String] = ["reasoning"],
        features: [String],
        featureConfig: [String: AnyCodable]? = nil,
        toolRendering: String? = nil,
        toolCallFormat: String? = nil,
        description: String?,
        fileSize: Int? = nil,
        fileSizeHuman: String? = nil
    ) async -> Bool {
        do {
            #if DEBUG
            DevLogger.shared.info("[CustomModels] createModel called:", context: "CustomModels")
            DevLogger.shared.info("  handler=\(handler), modelPath=\(modelPath ?? "nil"), downloadUrl=\(downloadUrl ?? "nil")", context: "CustomModels")
            #endif
            
            // Auto-generate key name, send actual key value separately
            let keyName = requiresAuth ? "custom_\(modelId)" : nil
            let request = CustomModelCreateRequest(
                modelId: modelId,
                displayName: displayName,
                handler: handler,
                baseUrl: baseUrl,
                modelIdentifier: modelIdentifier,
                modelPath: modelPath,
                downloadUrl: downloadUrl,
                contextWindow: contextWindow,
                maxOutputTokens: maxOutputTokens,
                requiresAuth: requiresAuth,
                apiKeyName: keyName,
                apiKey: requiresAuth ? apiKey : nil,
                capabilities: capabilities,
                features: features,
                featureConfig: featureConfig,
                toolRendering: toolRendering,
                toolCallFormat: toolCallFormat,
                description: description,
                fileSize: fileSize,
                fileSizeHuman: fileSizeHuman
            )
            
            let _: CustomModelCreateResponse = try await apiClient.post(
                "/models/custom",
                body: request,
                decoding: CustomModelCreateResponse.self
            )
            await loadModels()
            return true
        } catch let apiError as APIError {
            // Capture detailed API error info
            switch apiError {
            case .connectionFailed(let message):
                lastError = "Connection failed: \(message)"
            case .invalidResponse:
                lastError = "Invalid response from server"
            case .decodingFailed(let underlyingError):
                lastError = "Failed to decode response: \(underlyingError.localizedDescription)"
            case .backendNotAvailable:
                lastError = "Backend not available"
            case .invalidURL:
                lastError = "Invalid URL"
            case .serverError(let statusCode):
                lastError = "Server error: \(statusCode)"
            }
            DevLogger.shared.error("Failed to create custom model (APIError): \(apiError)", context: "CustomModels")
            return false
        } catch {
            lastError = error.localizedDescription
            DevLogger.shared.error("Failed to create custom model: \(error)", context: "CustomModels")
            return false
        }
    }
    
    func updateModel(
        modelId: String,
        displayName: String,
        handler: String?,
        baseUrl: String?,
        modelIdentifier: String?,
        modelPath: String?,
        downloadUrl: String?,
        contextWindow: Int,
        maxOutputTokens: Int,
        requiresAuth: Bool,
        apiKey: String?,
        capabilities: [String] = ["reasoning"],
        features: [String],
        featureConfig: [String: AnyCodable]? = nil,
        toolRendering: String? = nil,
        toolCallFormat: String? = nil,
        description: String?
    ) async -> Bool {
        do {
            // Auto-generate key name, send actual key value separately
            let keyName = requiresAuth ? "custom_\(modelId)" : nil
            let request = CustomModelUpdateRequest(
                displayName: displayName,
                handler: handler,
                baseUrl: baseUrl,
                modelIdentifier: modelIdentifier,
                modelPath: modelPath,
                downloadUrl: downloadUrl,
                contextWindow: contextWindow,
                maxOutputTokens: maxOutputTokens,
                requiresAuth: requiresAuth,
                apiKeyName: keyName,
                apiKey: requiresAuth ? apiKey : nil,
                capabilities: capabilities,
                features: features,
                featureConfig: featureConfig,
                toolRendering: toolRendering,
                toolCallFormat: toolCallFormat,
                description: description
            )
            
            let _: CustomModelCreateResponse = try await apiClient.put(
                "/models/custom/\(modelId)",
                body: request,
                decoding: CustomModelCreateResponse.self
            )
            await loadModels()
            return true
        } catch {
            lastError = error.localizedDescription
            DevLogger.shared.error("Failed to update custom model: \(error)", context: "CustomModels")
            return false
        }
    }
    
    func deleteModel(_ modelId: String, deleteFiles: Bool = false, clearHFCache: Bool = false) async {
        do {
            _ = try await apiClient.delete("/models/custom/\(modelId)?delete_files=\(deleteFiles)&clear_hf_cache=\(clearHFCache)")
            await loadModels()
        } catch {
            lastError = error.localizedDescription
            DevLogger.shared.error("Failed to delete custom model: \(error)", context: "CustomModels")
        }
    }
    
    func testConnection(_ model: CustomModelConfig) async -> (success: Bool, message: String) {
        guard let baseUrl = model.baseUrl, let modelIdentifier = model.modelIdentifier else {
            return (false, "Missing base URL or model identifier")
        }
        return await testConnectionDirect(
            handler: model.handler,
            baseUrl: baseUrl,
            modelIdentifier: modelIdentifier,
            apiKey: nil  // Don't send stored key for security; user should re-enter
        )
    }
    
    // MARK: - HuggingFace Operations
    
    func probeHFRepo(url: String) async throws -> HFProbeResponse {
        let request = HFProbeRequest(url: url)
        return try await apiClient.post(
            "/models/custom/probe-hf-repo",
            body: request,
            decoding: HFProbeResponse.self
        )
    }
    
    /// Fetch GGUF file metadata via partial download (first 256KB)
    func fetchGGUFMetadata(repoId: String, filename: String) async -> GGUFMetadataResponse? {
        let request = GGUFMetadataRequest(repoId: repoId, filename: filename)
        do {
            let response: GGUFMetadataResponse = try await apiClient.post(
                "/models/custom/gguf-metadata",
                body: request,
                decoding: GGUFMetadataResponse.self
            )
            return response
        } catch {
            DevLogger.shared.error("Failed to fetch GGUF metadata: \(error)", context: "CustomModels")
            return nil
        }
    }
    
    /// Fetch GGUF metadata from a local file on disk.
    func fetchLocalGGUFMetadata(filePath: String) async -> GGUFMetadataResponse? {
        do {
            let encodedPath = filePath.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? filePath
            let response: GGUFMetadataResponse = try await apiClient.post(
                "/models/custom/local-gguf-metadata?file_path=\(encodedPath)",
                body: EmptyBody(),
                decoding: GGUFMetadataResponse.self
            )
            return response
        } catch {
            DevLogger.shared.error("Failed to fetch local GGUF metadata: \(error)", context: "CustomModels")
            return nil
        }
    }
    
    /// Download progress tracking
    @Published var downloadProgressMap: [String: Double] = [:]
    @Published var downloadStatus: [String: String] = [:]
    @Published var currentDownloadModelId: String?
    
    /// Convenience property for current download progress (0.0 - 1.0)
    var downloadProgress: Double {
        guard let modelId = currentDownloadModelId else { return 0.0 }
        return downloadProgressMap[modelId] ?? 0.0
    }
    
    func downloadModel(modelId: String, filename: String) async -> Bool {
        do {
            // Track which model is downloading
            await MainActor.run {
                currentDownloadModelId = modelId
            }
            
            // Start polling for progress
            let progressTask = Task { @MainActor in
                await pollDownloadProgress(modelId: modelId)
            }
            
            let request = DownloadModelRequest(filename: filename)
            let response: DownloadModelResponse = try await apiClient.post(
                "/models/custom/\(modelId)/download",
                body: request,
                decoding: DownloadModelResponse.self
            )
            
            // Stop polling
            progressTask.cancel()
            
            // Clear progress state
            await MainActor.run {
                downloadProgressMap.removeValue(forKey: modelId)
                downloadStatus.removeValue(forKey: modelId)
                currentDownloadModelId = nil
            }
            
            if response.success {
                await loadModels()
                return true
            } else {
                lastError = response.error ?? response.message
                return false
            }
        } catch {
            // Clear progress state
            await MainActor.run {
                downloadProgressMap.removeValue(forKey: modelId)
                downloadStatus.removeValue(forKey: modelId)
                currentDownloadModelId = nil
            }
            
            lastError = error.localizedDescription
            DevLogger.shared.error("Failed to download model: \(error)", context: "CustomModels")
            return false
        }
    }
    
    /// Poll for download progress
    @MainActor
    private func pollDownloadProgress(modelId: String) async {
        while !Task.isCancelled {
            do {
                let response: DownloadProgressResponse = try await apiClient.get(
                    "/models/custom/\(modelId)/download/progress",
                    decoding: DownloadProgressResponse.self
                )
                
                downloadProgressMap[modelId] = response.progress
                downloadStatus[modelId] = response.status
                
                #if DEBUG
                DevLogger.shared.info("[CustomModels] Download progress: \(Int(response.progress * 100))% (\(response.status))", context: "CustomModels")
                #endif
                
                // Exit if completed or error
                if response.status == "completed" || response.status == "error" || response.status == "not_found" {
                    break
                }
                
                // Poll every 500ms
                try await Task.sleep(nanoseconds: 500_000_000)
            } catch {
                // Ignore errors during polling, just continue
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }
    
    func testConnectionDirect(
        handler: String,
        baseUrl: String,
        modelIdentifier: String,
        apiKey: String?
    ) async -> (success: Bool, message: String) {
        do {
            let request = ConnectionTestRequest(
                handler: handler,
                baseUrl: baseUrl,
                modelIdentifier: modelIdentifier,
                requiresAuth: apiKey != nil && !apiKey!.isEmpty,
                apiKey: apiKey
            )
            
            let response: ConnectionTestResponse = try await apiClient.post(
                "/models/custom/connection-test",
                body: request,
                decoding: ConnectionTestResponse.self
            )
            
            return (response.success, response.message)
        } catch {
            return (false, error.localizedDescription)
        }
    }
}

// MARK: - Request Types

struct CustomModelCreateRequest: Encodable {
    let modelId: String
    let displayName: String
    let handler: String
    let baseUrl: String?
    let modelIdentifier: String?
    let modelPath: String?
    let downloadUrl: String?
    let contextWindow: Int
    let maxOutputTokens: Int
    let requiresAuth: Bool
    let apiKeyName: String?
    let apiKey: String?
    let capabilities: [String]
    let features: [String]
    let featureConfig: [String: AnyCodable]?
    let toolRendering: String?
    let toolCallFormat: String?
    let description: String?
    let fileSize: Int?
    let fileSizeHuman: String?
    
    enum CodingKeys: String, CodingKey {
        case modelId = "model_id"
        case displayName = "display_name"
        case handler
        case baseUrl = "base_url"
        case modelIdentifier = "model_identifier"
        case modelPath = "model_path"
        case downloadUrl = "download_url"
        case contextWindow = "context_window"
        case maxOutputTokens = "max_output_tokens"
        case requiresAuth = "requires_auth"
        case apiKeyName = "api_key_name"
        case apiKey = "api_key"
        case capabilities
        case features
        case featureConfig = "feature_config"
        case toolRendering = "tool_rendering"
        case toolCallFormat = "tool_call_format"
        case description
        case fileSize = "file_size"
        case fileSizeHuman = "file_size_human"
    }
}

struct CustomModelUpdateRequest: Encodable {
    let displayName: String?
    let handler: String?
    let baseUrl: String?
    let modelIdentifier: String?
    let modelPath: String?
    let downloadUrl: String?
    let contextWindow: Int?
    let maxOutputTokens: Int?
    let requiresAuth: Bool?
    let apiKeyName: String?
    let apiKey: String?
    let capabilities: [String]?
    let features: [String]?
    let featureConfig: [String: AnyCodable]?
    let toolRendering: String?
    let toolCallFormat: String?
    let description: String?
    
    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case handler
        case baseUrl = "base_url"
        case modelIdentifier = "model_identifier"
        case modelPath = "model_path"
        case downloadUrl = "download_url"
        case contextWindow = "context_window"
        case maxOutputTokens = "max_output_tokens"
        case requiresAuth = "requires_auth"
        case apiKeyName = "api_key_name"
        case apiKey = "api_key"
        case capabilities
        case features
        case featureConfig = "feature_config"
        case toolRendering = "tool_rendering"
        case toolCallFormat = "tool_call_format"
        case description
    }
}

struct HFProbeRequest: Encodable {
    let url: String
}

struct DownloadModelRequest: Encodable {
    let filename: String
}

/// Response from creating a custom model.
struct CustomModelCreateResponse: Decodable {
    let modelId: String
    let config: [String: AnyCodable]
    // No CodingKeys needed - decoder uses .convertFromSnakeCase automatically
    // which transforms model_id -> modelId
}

struct ConnectionTestRequest: Encodable {
    let handler: String
    let baseUrl: String
    let modelIdentifier: String
    let requiresAuth: Bool
    let apiKey: String?
    
    enum CodingKeys: String, CodingKey {
        case handler
        case baseUrl = "base_url"
        case modelIdentifier = "model_identifier"
        case requiresAuth = "requires_auth"
        case apiKey = "api_key"
    }
}

// MARK: - Response Types

/// Response from the custom models list endpoint.
/// Uses manual decoding to handle dynamic model config structure.
struct CustomModelsListResponse: Decodable {
    let models: [String: CustomModelConfigFromAPI]
    let count: Int?  // Made optional for safety
}

/// Decoded model config from API response.
struct CustomModelConfigFromAPI: Decodable {
    let displayName: String
    let handler: String
    let baseUrl: String?
    let modelIdentifier: String?
    let modelPath: String?
    let downloadUrl: String?
    let contextWindow: Int
    let maxOutputTokens: Int
    let requiresAuth: Bool
    let apiKeyName: String?
    let capabilities: [String]
    let features: [String]
    let featureConfig: [String: AnyCodable]?
    let toolRendering: String?
    let toolCallFormat: String?
    let description: String?
    let fileSize: Int?
    let fileSizeHuman: String?
    
    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case handler
        case baseUrl = "base_url"
        case modelIdentifier = "model_identifier"
        case modelPath = "model_path"
        case downloadUrl = "download_url"
        case contextWindow = "context_window"
        case maxOutputTokens = "max_output_tokens"
        case requiresAuth = "requires_auth"
        case apiKeyName = "api_key_name"
        case capabilities
        case features
        case featureConfig = "feature_config"
        case toolRendering = "tool_rendering"
        case toolCallFormat = "tool_call_format"
        case description
        case fileSize = "file_size"
        case fileSizeHuman = "file_size_human"
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        displayName = try container.decodeIfPresent(String.self, forKey: .displayName) ?? ""
        handler = try container.decodeIfPresent(String.self, forKey: .handler) ?? "openai_compatible"
        baseUrl = try container.decodeIfPresent(String.self, forKey: .baseUrl)
        modelIdentifier = try container.decodeIfPresent(String.self, forKey: .modelIdentifier)
        modelPath = try container.decodeIfPresent(String.self, forKey: .modelPath)
        downloadUrl = try container.decodeIfPresent(String.self, forKey: .downloadUrl)
        contextWindow = try container.decodeIfPresent(Int.self, forKey: .contextWindow) ?? 4096
        maxOutputTokens = try container.decodeIfPresent(Int.self, forKey: .maxOutputTokens) ?? 4096
        requiresAuth = try container.decodeIfPresent(Bool.self, forKey: .requiresAuth) ?? false
        apiKeyName = try container.decodeIfPresent(String.self, forKey: .apiKeyName)
        capabilities = try container.decodeIfPresent([String].self, forKey: .capabilities) ?? ["reasoning"]
        features = try container.decodeIfPresent([String].self, forKey: .features) ?? []
        featureConfig = try container.decodeIfPresent([String: AnyCodable].self, forKey: .featureConfig)
        toolRendering = try container.decodeIfPresent(String.self, forKey: .toolRendering)
        toolCallFormat = try container.decodeIfPresent(String.self, forKey: .toolCallFormat)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        fileSize = try container.decodeIfPresent(Int.self, forKey: .fileSize)
        fileSizeHuman = try container.decodeIfPresent(String.self, forKey: .fileSizeHuman)
    }
}

struct DownloadModelResponse: Decodable {
    let success: Bool
    let message: String
    let modelPath: String?
    let error: String?
    // No CodingKeys needed - decoder uses .convertFromSnakeCase automatically
}

struct DownloadProgressResponse: Decodable {
    let modelId: String
    let progress: Double
    let status: String
    let message: String?
    // No CodingKeys needed - decoder uses .convertFromSnakeCase automatically
}

struct ConnectionTestResponse: Decodable {
    let success: Bool
    let message: String
    // We don't need to decode details for display purposes
}
