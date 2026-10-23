import Foundation

/// Represents a conversation item in the history list.
struct ConversationListItem: Identifiable, Codable {
    let id: String
    let title: String?
    let createdAt: String
    let updatedAt: String
    let messageCount: Int
    let lastMessagePreview: String?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case messageCount = "message_count"
        case lastMessagePreview = "last_message_preview"
    }

    /// Display title with fallback.
    var displayTitle: String {
        title ?? "New Conversation"
    }

    /// Formatted date for display.
    var formattedDate: String {
        DateFormattingUtils.formatTimestamp(updatedAt)
    }
}

struct ConversationHistory: Codable {
    let conversationId: String
    let messages: [ConversationHistoryMessage]
    let createdAt: String
    let updatedAt: String
    let metadata: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
        case messages
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case metadata
    }
}

struct ConversationHistoryMessage: Codable, Identifiable {
    let id: String
    let content: String
    let role: String
    let timestamp: String
    let metadata: [String: AnyCodable]
}
