import Foundation
import SwiftUI

// MARK: - Models

enum ModelCapabilityType: String, Codable {
    case reasoning = "reasoning"
    case vision = "vision"
    case transcription = "transcription"
}

enum ModelDownloadStatus: Codable, Equatable {
    case available(path: String)
    case downloadable
    case downloading(progress: Double)
    case error(message: String)
    
    private enum CodingKeys: String, CodingKey {
        case type, path, progress, message
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .available(let path):
            try container.encode("available", forKey: .type)
            try container.encode(path, forKey: .path)
        case .downloadable:
            try container.encode("downloadable", forKey: .type)
        case .downloading(let progress):
            try container.encode("downloading", forKey: .type)
            try container.encode(progress, forKey: .progress)
        case .error(let message):
            try container.encode("error", forKey: .type)
            try container.encode(message, forKey: .message)
        }
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)
        switch type {
        case "available":
            let path = try container.decode(String.self, forKey: .path)
            self = .available(path: path)
        case "downloadable":
            self = .downloadable
        case "downloading":
            let progress = try container.decode(Double.self, forKey: .progress)
            self = .downloading(progress: progress)
        case "error":
            let message = try container.decode(String.self, forKey: .message)
            self = .error(message: message)
        default:
            throw DecodingError.dataCorruptedError(forKey: .type, in: container, debugDescription: "Unknown status type")
        }
    }
}

struct ModelDownloadInfo: Identifiable, Codable, Equatable {
    var id: String              // model_type-variant
    let modelType: String       // Base model type (e.g., "whisper")
    let variantId: String       // Specific variant (e.g., "large-v3-turbo")
    let name: String            // Display name
    let capabilities: [ModelCapabilityType]
    var status: ModelDownloadStatus = .downloadable
    var size: Int64?           // Size in bytes
    let variants: [String: [String]]
    
    init(id: String, modelType: String, variantId: String, name: String, capabilities: [ModelCapabilityType], status: ModelDownloadStatus = .downloadable, size: Int64? = nil, variants: [String: [String]]) {
        self.id = id
        self.modelType = modelType
        self.variantId = variantId
        self.name = name
        self.capabilities = capabilities
        self.status = status
        self.size = size
        self.variants = variants
    }
    
    private enum CodingKeys: String, CodingKey {
        case name, capabilities, path, size, valid, variants
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        
        // These fields must be initialized first
        name = try container.decode(String.self, forKey: .name)
        variants = try container.decode([String: [String]].self, forKey: .variants)
        
        // Extract model type and variant ID from the coding path
        let codingPath = decoder.codingPath
        guard codingPath.count >= 2,
              let groupKey = codingPath[codingPath.count - 2].stringValue.split(separator: ".").last,
              let variantKey = codingPath[codingPath.count - 1].stringValue.split(separator: ".").last else {
            throw DecodingError.dataCorruptedError(forKey: .name, in: container, debugDescription: "Could not determine model type and variant")
        }
        
        modelType = String(groupKey)
        variantId = String(variantKey)
        id = "\(modelType)-\(variantId)"
        
        // Try to decode capabilities from the variants
        var modelCapabilities: [ModelCapabilityType] = []
        for (_, variantTypes) in variants {
            for type in variantTypes {
                if let capability = ModelCapabilityType(rawValue: type) {
                    modelCapabilities.append(capability)
                }
            }
        }
        capabilities = Array(Set(modelCapabilities))
        
        // Handle size field which might come as a string
        if let sizeStr = try? container.decode(String.self, forKey: .size) {
            // Parse size string using decimal conversion (1000^3) to match actual file sizes
            let numStr = sizeStr.lowercased().replacingOccurrences(of: "gb", with: "")
            if let sizeGB = Double(numStr) {
                size = Int64(sizeGB * 1000 * 1000 * 1000) // Convert GB to bytes
            }
        }
        
        // Check for valid flag and path in installed models
        if let valid = try? container.decode(Bool.self, forKey: .valid),
           valid,
           let path = try? container.decode(String.self, forKey: .path) {
            status = .available(path: path)
        } else if let path = try? container.decode(String.self, forKey: .path) {
            status = .available(path: path)
        } else {
            status = .downloadable
        }
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(name, forKey: .name)
        try container.encode(variants, forKey: .variants)
        if let size = size {
            // Convert bytes back to GB string for backend using decimal conversion
            let sizeGB = Double(size) / Double(1000 * 1000 * 1000)
            let sizeStr = String(format: "%.1fGB", sizeGB)
            try container.encode(sizeStr, forKey: .size)
        }
        if case .available(let path) = status {
            try container.encode(path, forKey: .path)
        }
    }
} 