import Foundation

struct MemoryDocumentDTO: Codable, Identifiable {
    var id: String { fileName }
    let fileName: String
    let content: String
    let sizeBytes: Int
    let capBytes: Int?
    let updatedAt: String?
}

struct MemoryDocumentListDTO: Codable {
    let documents: [MemoryDocumentDTO]
}

struct MemoryProposalDTO: Codable, Identifiable {
    let id: String
    let targetFileName: String
    let entry: String
    let why: String?
    let confidence: String?
    let source: String
    let createdAt: String
    let status: String
}

struct MemoryProposalListDTO: Codable {
    let proposals: [MemoryProposalDTO]
}

struct SkillCandidateDTO: Codable, Identifiable {
    let id: String
    let title: String
    let whenToUse: String
    let triggers: [String]
    let procedureMarkdown: String
    let expectedResult: String
    let sourceTaskIds: [String]
    let source: String
    let createdAt: String
    let status: String
    let observationCount: Int
}

struct SkillCandidateListDTO: Codable {
    let candidates: [SkillCandidateDTO]
}

struct MemoryRunNowDTO: Codable {
    let memoryProposalsAdded: Int
    let skillCandidatesAdded: Int
    let errors: [String]
}

struct MemoryIntelligenceSettingsDTO: Codable {
    var memoryAfterTaskEnabled: Bool
    var memoryDailyEnabled: Bool
    var memoryDailyTimeLocal: String
    var memoryProcessingModel: String?
    var skillAfterTaskEnabled: Bool
    var skillDailyEnabled: Bool
    var skillDailyTimeLocal: String
    var skillProcessingModel: String?
    var skillReconciliationMinInstances: Int
}

struct MemoryIntelligenceSettingsResponseDTO: Codable {
    let settings: MemoryIntelligenceSettingsDTO
}

struct MemoryIntelligenceSettingsUpdateResponseDTO: Codable {
    let status: String
    let updatedSettings: MemoryIntelligenceSettingsDTO
    let message: String?
}

struct SkillListDTO: Codable {
    let skills: [SkillDTO]
}

struct SkillDTO: Codable, Identifiable {
    var id: String { slug }
    let slug: String
    let title: String
    let whenToUse: String
    let triggers: [String]
    let sizeBytes: Int
    let capBytes: Int
    let lastUsed: String?
    let observationCount: Int
    let version: Int
}

extension APIClient {
    func getMemoryIntelligenceSettings() async throws -> MemoryIntelligenceSettingsDTO {
        let data = try await get("/settings/memory-intelligence")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MemoryIntelligenceSettingsResponseDTO.self, from: data).settings
    }

    func updateMemoryIntelligenceSettings(_ settings: MemoryIntelligenceSettingsDTO) async throws -> MemoryIntelligenceSettingsDTO {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let payload = try encoder.encode(settings)
        let data = try await put("/settings/memory-intelligence", data: payload)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MemoryIntelligenceSettingsUpdateResponseDTO.self, from: data).updatedSettings
    }

    func listMemoryDocuments() async throws -> [MemoryDocumentDTO] {
        let data = try await get("/memory/")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MemoryDocumentListDTO.self, from: data).documents
    }

    func listMemoryProposals() async throws -> [MemoryProposalDTO] {
        let data = try await get("/memory/promotions")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MemoryProposalListDTO.self, from: data).proposals
    }

    func declineMemoryProposal(id: String) async throws {
        _ = try await postForData("/memory/promotions/\(id)/decline")
    }

    func getMemoryDocument(fileName: String) async throws -> MemoryDocumentDTO {
        let data = try await get("/memory/\(fileName)")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MemoryDocumentDTO.self, from: data)
    }

    func updateMemoryDocument(fileName: String, content: String) async throws -> MemoryDocumentDTO {
        struct UpdateRequest: Codable {
            let content: String
        }

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let payload = try encoder.encode(UpdateRequest(content: content))
        let data = try await put("/memory/\(fileName)", data: payload)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MemoryDocumentDTO.self, from: data)
    }

    func runMemoryIntelligenceNow() async throws -> MemoryRunNowDTO {
        let data = try await postForData("/memory/run-now")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(MemoryRunNowDTO.self, from: data)
    }

    func listSkillCandidates() async throws -> [SkillCandidateDTO] {
        let data = try await get("/memory/skill-candidates")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SkillCandidateListDTO.self, from: data).candidates
    }

    func declineSkillCandidate(id: String) async throws {
        _ = try await postForData("/memory/skill-candidates/\(id)/decline")
    }

    func listSkills() async throws -> [SkillDTO] {
        let data = try await get("/memory/skills")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SkillListDTO.self, from: data).skills
    }

    func deleteSkill(slug: String) async throws {
        _ = try await delete("/memory/skills/\(slug)")
    }
}
