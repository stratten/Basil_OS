import Foundation

struct ProviderType: Codable {
    let variants: [String: ModelVariant]
}

enum CapabilityValue: Codable {
    case int(Int)
    case string(String)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let intVal = try? container.decode(Int.self) {
            self = .int(intVal)
        } else if let strVal = try? container.decode(String.self) {
            self = .string(strVal)
        } else {
            throw DecodingError.typeMismatch(CapabilityValue.self, DecodingError.Context(codingPath: decoder.codingPath, debugDescription: "Not a string or int"))
        }
    }

    func toModelCapabilityType() -> ModelCapabilityType? {
        switch self {
        case .int(3): return .reasoning
        case .int(4): return .transcription
        case .string(let str): return ModelCapabilityType(rawValue: str)
        default: return nil
        }
    }
}

struct ModelVariant: Codable {
    let name: String
    let size: String
    let url: String?
    let sha256: String?
    let capabilities: [CapabilityValue]?
    let recommendedRam: String?
    let supportsGpu: Bool?
    let description: String?
    let source: String?
    let version: String?
    let repo: RepoInfo?
    let path: String?
    let valid: Bool?
}

struct RepoInfo: Codable {
    let url: String
    let revision: String
}

