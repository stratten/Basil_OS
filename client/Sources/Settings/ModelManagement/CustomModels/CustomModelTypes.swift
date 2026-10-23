//
//  CustomModelTypes.swift
//  BasilClient
//
//  Data types, enums, and response structs for custom model management.
//

import Foundation

// MARK: - Wizard Types

/// Steps in the custom model creation wizard.
enum WizardStep: Int, CaseIterable {
    case modelType = 0      // API vs Local
    case localSource = 1    // HuggingFace vs Local File (only for local)
    case huggingface = 2    // HuggingFace URL + file selection
    case localFile = 3      // Local file picker
    case details = 4        // Final editable form
    
    var title: String {
        switch self {
        case .modelType: return "Model Type"
        case .localSource: return "Model Source"
        case .huggingface: return "HuggingFace Repository"
        case .localFile: return "Local File"
        case .details: return "Model Details"
        }
    }
    
    var stepNumber: Int {
        switch self {
        case .modelType: return 1
        case .localSource: return 2
        case .huggingface, .localFile: return 3
        case .details: return 4
        }
    }
    
    var totalSteps: Int { 4 }
}

/// Data collected across wizard steps.
struct WizardData {
    // Step 1: Model type
    var isLocal: Bool = true
    var handlerType: CustomModelHandlerType = .localGguf
    
    // Step 2: Local source (for local models)
    var localSource: LocalModelSource = .huggingface
    
    // Step 3a: HuggingFace data
    var huggingFaceUrl: String = ""
    var hfProbeResult: HFProbeResponse?
    var selectedHFFile: String?
    
    // Step 3b: Local file data
    var localFilePath: String = ""
    
    // Extracted metadata (from GGUF header)
    var extractedContextWindow: Int?
    var extractedArchitecture: String?
    var extractedModelName: String?
    
    // File size (captured during HuggingFace probing or from local file)
    var fileSize: Int?
    var fileSizeHuman: String?
    
    // API model fields
    var baseUrl: String = ""
    var modelIdentifier: String = ""
    
    // Final form fields (editable, pre-populated from extracted data)
    var displayName: String = ""
    var modelId: String = ""
    var description: String = ""
    var contextWindow: Int = 4096
    var maxOutputTokens: Int = 4096
    var requiresAuth: Bool = false
    var apiKey: String = ""
    var features: [CustomModelFeature] = CustomModelFeature.defaultFeatures
    
    /// Apply extracted metadata to form fields.
    mutating func applyExtractedMetadata() {
        if let name = extractedModelName, displayName.isEmpty {
            displayName = name
            // Also auto-generate modelId from extracted name
            if modelId.isEmpty {
                modelId = generateModelId(from: name)
            }
        }
        if let ctx = extractedContextWindow {
            contextWindow = ctx
            // Apply heuristic: maxOutputTokens = min(4096, contextWindow / 2)
            // Capped at 4096 to prevent runaway generation while leaving room for input
            maxOutputTokens = min(4096, ctx / 2)
        }
    }
    
    /// Generate a valid model ID from a display name.
    private func generateModelId(from displayName: String) -> String {
        displayName
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .replacingOccurrences(of: "_", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "." }
    }
}

// MARK: - Handler Types

/// Handler types for custom models.
enum CustomModelHandlerType: String, CaseIterable, Identifiable {
    case openaiCompatible = "openai_compatible"
    case anthropicCompatible = "anthropic_compatible"
    case localGguf = "llama_cpp"
    
    var id: String { rawValue }
    
    var displayName: String {
        switch self {
        case .openaiCompatible: return "OpenAI-Compatible"
        case .anthropicCompatible: return "Anthropic-Compatible"
        case .localGguf: return "Local GGUF Model"
        }
    }
    
    var description: String {
        switch self {
        case .openaiCompatible: return "For Ollama, LM Studio, vLLM, Together AI, Groq, etc."
        case .anthropicCompatible: return "For AWS Bedrock, Anthropic proxies, etc."
        case .localGguf: return "For local GGUF models via llama.cpp"
        }
    }
    
    var isLocal: Bool {
        self == .localGguf
    }
    
    var isAPI: Bool {
        self == .openaiCompatible || self == .anthropicCompatible
    }
}

// MARK: - Local Model Source

/// Source for local model files.
enum LocalModelSource: String, CaseIterable, Identifiable {
    case huggingface = "huggingface"
    case localFile = "local_file"
    
    var id: String { rawValue }
    
    var displayName: String {
        switch self {
        case .huggingface: return "Download from HuggingFace"
        case .localFile: return "Select Local File"
        }
    }
}

// MARK: - Model Features

/// Feature configuration for custom models.
struct CustomModelFeature: Identifiable, Hashable {
    let id: String
    let name: String
    var isEnabled: Bool
    
    static let defaultFeatures: [CustomModelFeature] = [
        CustomModelFeature(id: "streaming", name: "Streaming", isEnabled: true),
        CustomModelFeature(id: "system_prompts", name: "System Prompts", isEnabled: true),
        CustomModelFeature(id: "function_calling", name: "Function Calling", isEnabled: false),
        CustomModelFeature(id: "json_mode", name: "JSON Mode", isEnabled: false),
    ]
}

enum CustomModelToolCallFormat: String, CaseIterable, Identifiable {
    case jsonToolCall = "json_tool_call"
    case functionParameterTags = "function_parameter_tags"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .jsonToolCall: return "JSON <tool_call>"
        case .functionParameterTags: return "Function/Parameter Tags"
        }
    }
}

// MARK: - HuggingFace Probe Response Types

/// Information about a file in a HuggingFace repository.
/// Note: No CodingKeys needed - APIClient uses .convertFromSnakeCase automatically
struct HFFileInfo: Decodable, Identifiable {
    let name: String
    let sizeBytes: Int?
    let sizeHuman: String?
    
    var id: String { name }
}

/// Model metadata extracted from HuggingFace config files.
/// Note: No CodingKeys needed - APIClient uses .convertFromSnakeCase automatically
struct HFModelMetadata: Decodable {
    let contextWindow: Int?
    let modelType: String?
    let architecture: String?
}

/// Response from probing a HuggingFace repository.
/// Note: No CodingKeys needed - APIClient uses .convertFromSnakeCase automatically
struct HFProbeResponse: Decodable {
    let repoId: String
    let ggufFiles: [HFFileInfo]
    let safetensorFiles: [HFFileInfo]
    let modelMetadata: HFModelMetadata?
    let error: String?
}

// MARK: - GGUF Metadata Types

/// Request to fetch GGUF file metadata via partial download.
struct GGUFMetadataRequest: Encodable {
    let repoId: String
    let filename: String
}

/// Response containing extracted GGUF file metadata.
/// Note: No CodingKeys needed - APIClient uses .convertFromSnakeCase automatically
struct GGUFMetadataResponse: Decodable {
    let success: Bool
    let filename: String?
    let contextWindow: Int?
    let architecture: String?
    let modelName: String?
    let error: String?
}

// MARK: - Custom Model Config

/// Configuration for a user-defined custom model.
struct CustomModelConfig: Codable, Identifiable {
    var id: String { modelId }
    let modelId: String
    var displayName: String
    var handler: String
    var baseUrl: String?
    var modelIdentifier: String?
    var modelPath: String?
    var downloadUrl: String?
    var contextWindow: Int
    var maxOutputTokens: Int
    var requiresAuth: Bool
    var apiKeyName: String?
    var capabilities: [String]
    var features: [String]
    var featureConfig: [String: AnyCodable]?
    var toolRendering: String?
    var toolCallFormat: String?
    var serverType: String?
    var description: String?
    var fileSize: Int?
    var fileSizeHuman: String?
    
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
        case capabilities
        case features
        case featureConfig = "feature_config"
        case toolRendering = "tool_rendering"
        case toolCallFormat = "tool_call_format"
        case serverType = "server_type"
        case description
        case fileSize = "file_size"
        case fileSizeHuman = "file_size_human"
    }
    
    /// Whether this is a local model (llama_cpp handler).
    var isLocal: Bool {
        handler == CustomModelHandlerType.localGguf.rawValue
    }
}
