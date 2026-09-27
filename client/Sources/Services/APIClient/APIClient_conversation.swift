import Foundation

// MARK: - Conversation History Methods for APIClient
extension APIClient {
    
    // MARK: - List Conversations
    
    /// Fetch a list of conversations ordered by most recent
    /// - Parameters:
    ///   - limit: Maximum number of conversations to return (default: 50)
    ///   - offset: Pagination offset (default: 0)
    /// - Returns: Array of ConversationListItem
    func listConversations(limit: Int = 50, offset: Int = 0) async throws -> [ConversationListItem] {
        #if DEBUG
        DevLogger.shared.info("📋 Fetching conversation list (limit: \(limit), offset: \(offset))", context: "APIClient")
        #endif
        
        let data = try await get("/conversation/list?limit=\(limit)&offset=\(offset)")
        let decoder = JSONDecoder()
        
        do {
            let conversations = try decoder.decode([ConversationListItem].self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched \(conversations.count) conversations", context: "APIClient")
            #endif
            return conversations
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode conversations: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    // MARK: - Update Conversation Title
    
    /// Update the title of a conversation
    /// - Parameters:
    ///   - conversationId: ID of the conversation to update
    ///   - title: New title for the conversation
    func updateConversationTitle(conversationId: String, title: String) async throws {
        #if DEBUG
        DevLogger.shared.info("✏️ Updating conversation title: \(conversationId) -> '\(title)'", context: "APIClient")
        #endif
        
        let requestBody: [String: Any] = ["title": title]
        let jsonData = try JSONSerialization.data(withJSONObject: requestBody)
        
        _ = try await put("/conversation/\(conversationId)/title", data: jsonData)
        
        #if DEBUG
        DevLogger.shared.info("✅ Successfully updated conversation title", context: "APIClient")
        #endif
    }
    
    // MARK: - Delete Conversation
    
    /// Delete a conversation and all its messages
    /// - Parameter conversationId: ID of the conversation to delete
    func deleteConversation(conversationId: String) async throws {
        #if DEBUG
        DevLogger.shared.info("🗑️ Deleting conversation: \(conversationId)", context: "APIClient")
        #endif
        
        _ = try await delete("/conversation/\(conversationId)")
        
        #if DEBUG
        DevLogger.shared.info("✅ Successfully deleted conversation", context: "APIClient")
        #endif
    }
    
    /// Get a conversation by ID with all its messages
    func getConversation(conversationId: String) async throws -> ConversationHistory {
        #if DEBUG
        DevLogger.shared.info("📖 Fetching conversation: \(conversationId)", context: "APIClient")
        #endif
        
        let data = try await get("/conversation/\(conversationId)")
        let conversation = try JSONDecoder().decode(ConversationHistory.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("✅ Fetched conversation with \(conversation.messages.count) messages", context: "APIClient")
        #endif
        
        return conversation
    }
    
    // MARK: - Search Conversations
    
    /// Search conversations by title or message content
    /// - Parameters:
    ///   - query: Text to search for in conversation titles and message content
    ///   - days: Only search within the last N days (optional)
    ///   - limit: Maximum number of conversations to return (default: 50)
    /// - Returns: Array of matching ConversationListItem
    func searchConversations(query: String?, days: Int? = nil, limit: Int = 50) async throws -> [ConversationListItem] {
        #if DEBUG
        DevLogger.shared.info("🔍 Searching conversations (query: \(query ?? "nil"), days: \(days ?? 0), limit: \(limit))", context: "APIClient")
        #endif
        
        var urlComponents = URLComponents(string: "/conversation/search")!
        var queryItems: [URLQueryItem] = []
        
        if let query = query, !query.isEmpty {
            queryItems.append(URLQueryItem(name: "query", value: query))
        }
        if let days = days {
            queryItems.append(URLQueryItem(name: "days", value: String(days)))
        }
        queryItems.append(URLQueryItem(name: "limit", value: String(limit)))
        
        urlComponents.queryItems = queryItems
        
        let data = try await get(urlComponents.string ?? "/conversation/search")
        let decoder = JSONDecoder()
        
        do {
            let conversations = try decoder.decode([ConversationListItem].self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Search returned \(conversations.count) conversations", context: "APIClient")
            #endif
            return conversations
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode conversation search results: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
}

