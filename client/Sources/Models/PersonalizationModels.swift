import Foundation

// MARK: - Enums

enum FormalityLevel: String, Codable, CaseIterable {
    case casual = "casual"
    case professional = "professional"
    case formal = "formal"
    
    var displayName: String {
        switch self {
        case .casual: return "Casual"
        case .professional: return "Professional"
        case .formal: return "Formal"
        }
    }
}

enum ToneType: String, Codable, CaseIterable {
    case friendly = "friendly"
    case business = "business"
    case technical = "technical"
    case warm = "warm"
    case direct = "direct"
    case conversational = "conversational"
    
    var displayName: String {
        switch self {
        case .friendly: return "Friendly"
        case .business: return "Business"
        case .technical: return "Technical"
        case .warm: return "Warm"
        case .direct: return "Direct"
        case .conversational: return "Conversational"
        }
    }
}

// MARK: - User Profile

struct UserProfile: Codable {
    let id: String
    
    // Identity - using snake_case to match backend exactly
    var full_name: String?
    var preferred_name: String?
    var email: String?
    
    // Professional context
    var job_title: String?
    var company_name: String?
    var industry: String?
    
    // Communication preferences
    var default_formality: FormalityLevel?
    var default_tone: ToneType?
    var custom_instructions: String?
    
    // Metadata
    let created_at: Date?
    let updated_at: Date?
    let profile_version: Int?
    
    // Helper computed property to check if profile is empty
    var isEmpty: Bool {
        return full_name == nil &&
               preferred_name == nil &&
               email == nil &&
               job_title == nil &&
               company_name == nil &&
               industry == nil &&
               default_formality == nil &&
               default_tone == nil &&
               custom_instructions == nil
    }
    
    // Computed property for formatted dates
    var formattedCreatedDate: String {
        guard let created_at = created_at else { return "Not set" }
        
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: created_at)
    }
}

// MARK: - User Profile Create

struct UserProfileCreate: Codable {
    var full_name: String? = nil
    var preferred_name: String? = nil
    var email: String? = nil
    var job_title: String? = nil
    var company_name: String? = nil
    var industry: String? = nil
    var default_formality: String? = nil  // Send as string to backend
    var default_tone: String? = nil       // Send as string to backend
    var custom_instructions: String? = nil
}

// MARK: - Writing Sample Count Response

struct WritingSampleCountResponse: Codable {
    let count: Int
}

// MARK: - Save Sample Response

struct SaveSampleResponse: Codable {
    let status: String
    let sample_id: String?
    let context_type: String?
    let signature_detected: Bool?
    let contact_tracked: Bool?
    let error: String?
    let message: String?
}

// MARK: - Personalization Context Response

struct PersonalizationContextResponse: Codable {
    let profile: UserProfile?
    let style: CommunicationStyleProfile?
    let writing_samples: [WritingSample]?
    let contact: ContactRelationship?
    let signature: UserSignature?
}

struct CommunicationStyleProfile: Codable {
    let id: String
    let user_id: String
    let context_type: String
    let style_attributes: StyleAttributes
    let confidence: Double
    let sample_count: Int
    let created_at: Date
    let updated_at: Date
    let last_used_at: Date?
    
    // Computed property for confidence percentage
    var confidencePercentage: Int {
        return Int(confidence * 100)
    }
    
    // Computed property for confidence description
    var confidenceDescription: String {
        if confidence < 0.4 {
            return "Low confidence - need more samples"
        } else if confidence < 0.7 {
            return "Moderate confidence"
        } else if confidence < 0.9 {
            return "High confidence"
        } else {
            return "Very high confidence"
        }
    }
}

struct WritingSample: Codable, Identifiable {
    let id: String
    let user_id: String
    let source_type: String
    let context_type: String
    let app_name: String?
    let content: String
    let content_hash: String
    let recipient: String?
    let subject: String?
    let relationship_type: String?
    let was_edited: Bool
    let edit_distance: Int?
    let created_at: Date
    
    // Computed properties for display
    var formattedDate: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: created_at)
    }
    
    var contentPreview: String {
        let maxLength = 100
        if content.count <= maxLength {
            return content
        }
        return String(content.prefix(maxLength)) + "..."
    }
    
    var contextDisplayName: String {
        switch context_type {
        case "email_reply": return "Email Reply"
        case "email_compose": return "Email Compose"
        case "social_media": return "Social Media"
        case "document": return "Document"
        default: return context_type.capitalized
        }
    }
}

struct WritingSamplesListResponse: Codable {
    let samples: [WritingSample]
    let total: Int
    let limit: Int
    let offset: Int
}

struct ContactRelationship: Codable {
    let id: String
    let contact_email: String
    let contact_name: String?
    let relationship_type: String
    let formality_level: String
    let message_count: Int
    let last_contact_date: Date
}

struct UserSignature: Codable {
    let id: String
    let signature_text: String
    let context: String
    let occurrence_count: Int
}

// MARK: - Communication Style

struct StyleAttributes: Codable {
    let formality_level: Double
    let avg_sentence_length: Double
    let greeting_patterns: [String]
    let closing_patterns: [String]
    let common_phrases: [String]
    let vocabulary_complexity: String
    let uses_contractions: Bool
    let uses_emojis: Bool
    let paragraph_structure: String
    let tone_markers: [String]
    let avg_word_length: Double?
    let style_summary: String?
    
    // Computed property for formality display
    var formalityDescription: String {
        if formality_level < 0.35 {
            return "Casual"
        } else if formality_level < 0.65 {
            return "Professional"
        } else {
            return "Formal"
        }
    }
    
    // Computed property for formality percentage
    var formalityPercentage: Int {
        return Int(formality_level * 100)
    }
}
