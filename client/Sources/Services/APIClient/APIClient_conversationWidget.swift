import Foundation

// MARK: - Conversation Widget Settings Models

struct ConversationWidgetSettingsResponse: Codable {
    let status: String
    let settings: ConversationWidgetSettings
}

struct ConversationWidgetSettings: Codable {
    let widgetSize: WidgetSize?
    let widgetPosition: WidgetPosition?
    let isSidebarCollapsed: Bool
    var defaultConversationOnly: Bool? = nil
    
    enum CodingKeys: String, CodingKey {
        case widgetSize = "widget_size"
        case widgetPosition = "widget_position"
        case isSidebarCollapsed = "is_sidebar_collapsed"
        case defaultConversationOnly = "default_conversation_only"
    }
}

// MARK: - API Client Extension

extension APIClient {
    
    // MARK: - Get Conversation Widget Settings
    
    func getConversationWidgetSettings() async throws -> ConversationWidgetSettings {
        let data = try await get("/settings/conversation-widget")
        let response = try JSONDecoder().decode(ConversationWidgetSettingsResponse.self, from: data)
        return response.settings
    }
    
    // MARK: - Update Conversation Widget Size
    
    func updateConversationWidgetSize(_ size: NSSize) async throws {
        let widgetSize = WidgetSize(nsSize: size)
        let settings: [String: Any] = [
            "widget_size": widgetSize.asArray
        ]
        let jsonData = try JSONSerialization.data(withJSONObject: settings)
        _ = try await put("/settings/conversation-widget", data: jsonData)
        
        #if DEBUG
        DevLogger.shared.info("📏 Updated conversation widget size: \(size.width) x \(size.height)", context: "ConversationWidget")
        #endif
    }
    
    // MARK: - Update Conversation Widget Position
    
    func updateConversationWidgetPosition(_ position: NSPoint, screenID: Int) async throws {
        let widgetPosition = WidgetPosition(nsPoint: position, screenID: screenID)
        let settings: [String: Any] = [
            "widget_position": widgetPosition.asArray
        ]
        let jsonData = try JSONSerialization.data(withJSONObject: settings)
        _ = try await put("/settings/conversation-widget", data: jsonData)
        
        #if DEBUG
        DevLogger.shared.info("📍 Updated conversation widget position: (\(position.x), \(position.y)) on screen \(screenID)", context: "ConversationWidget")
        #endif
    }
    
    // MARK: - Update Sidebar Collapsed State
    
    func updateConversationSidebarCollapsed(_ isCollapsed: Bool) async throws {
        let settings: [String: Any] = [
            "is_sidebar_collapsed": isCollapsed
        ]
        let jsonData = try JSONSerialization.data(withJSONObject: settings)
        _ = try await put("/settings/conversation-widget", data: jsonData)
        
        #if DEBUG
        DevLogger.shared.info("📂 Updated conversation sidebar collapsed: \(isCollapsed)", context: "ConversationWidget")
        #endif
    }
    
    // MARK: - Update Conversation Only Default

    func updateConversationDefaultConversationOnly(_ enabled: Bool) async throws {
        let settings: [String: Any] = [
            "default_conversation_only": enabled
        ]
        let jsonData = try JSONSerialization.data(withJSONObject: settings)
        _ = try await put("/settings/conversation-widget", data: jsonData)
    }

    // MARK: - Cached Settings
    
    private static var cachedConversationWidgetSettings: ConversationWidgetSettings?
    
    func getCachedConversationWidgetSettings() -> ConversationWidgetSettings {
        // Check if we have settings in memory cache
        if let settings = Self.cachedConversationWidgetSettings {
            #if DEBUG
            DevLogger.shared.info("Using cached conversation widget settings", context: "APIClient")
            #endif
            return settings
        }
        
        // Try to get fresh settings from the server synchronously
        if let data = try? getSync("/settings/conversation-widget"),
           let response = try? JSONDecoder().decode(ConversationWidgetSettingsResponse.self, from: data) {
            #if DEBUG
            DevLogger.shared.info("Retrieved fresh conversation widget settings from server", context: "APIClient")
            #endif
            // Update our cache with these fresh settings
            Self.cachedConversationWidgetSettings = response.settings
            return response.settings
        } else {
            #if DEBUG
            DevLogger.shared.error("Failed to get conversation widget settings from server", context: "APIClient")
            #endif
        }
        
        // Fall back to default settings if everything else fails
        #if DEBUG
        DevLogger.shared.warning("Using default conversation widget settings (no cached or server settings available)", context: "APIClient")
        #endif
        let defaultSettings = ConversationWidgetSettings(
            widgetSize: WidgetSize(width: 700, height: 600),
            widgetPosition: nil,
            isSidebarCollapsed: false
        )
        // Cache these default settings
        Self.cachedConversationWidgetSettings = defaultSettings
        return defaultSettings
    }
    
    func cacheConversationWidgetSettings(_ settings: ConversationWidgetSettings) {
        Self.cachedConversationWidgetSettings = settings
    }
}

