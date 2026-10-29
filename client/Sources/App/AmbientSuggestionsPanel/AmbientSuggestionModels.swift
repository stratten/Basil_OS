import Foundation

struct AmbientSuggestionRecord: Codable, Identifiable {
    let suggestionId: String
    let createdAt: String
    let contentFingerprint: String
    let sourceIdentifier: String?
    let appName: String
    let windowTitle: String
    let capability: String
    let suggestionType: String
    let title: String
    let summary: String
    let details: String?
    let proposedRequest: String?
    let instruction: String
    let contextText: String
    let confidence: Double
    let outcome: String
    let autoExecuteEligible: Bool

    var id: String { suggestionId }

    enum CodingKeys: String, CodingKey {
        case suggestionId = "suggestion_id"
        case createdAt = "created_at"
        case contentFingerprint = "content_fingerprint"
        case sourceIdentifier = "source_identifier"
        case appName = "app_name"
        case windowTitle = "window_title"
        case capability
        case suggestionType = "suggestion_type"
        case title
        case summary
        case details
        case proposedRequest = "proposed_request"
        case instruction
        case contextText = "context_text"
        case confidence
        case outcome
        case autoExecuteEligible = "auto_execute_eligible"
    }
}

struct AmbientSuggestionOutcomeRequest: Codable {
    let outcome: String
}

struct AmbientSuggestionOperationResponse: Codable {
    let success: Bool
    let suggestion: AmbientSuggestionRecord?
    let message: String
}
